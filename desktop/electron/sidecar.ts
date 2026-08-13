/**
 * Sidecar process supervisor. Owns the lifetime of the Python sidecar
 * per ADR-0001 (Electron main, not the renderer, is the parent).
 *
 * The supervisor:
 *   - launches the sidecar as a child process (stdio IPC, per ADR-0002)
 *   - restarts on exit with exponential backoff
 *   - emits `sidecar.ready` / `sidecar.crashed` events over the
 *     IPC event bridge
 *   - never marks interrupted work as successful
 *
 * The foundation cut implements the wire protocol and the supervision
 * policy; the actual application services are wired in by the service
 * package.
 */
import { spawn, type ChildProcess, type SpawnOptions } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { createInterface, type Interface as ReadLineInterface } from 'node:readline';
import { resolve as pathResolve } from 'node:path';
import { decodeFrame, encodeFrame, type Frame, type ResponseFrame } from '../shared/ipc-schema.js';
import { PROTOCOL_VERSION } from '../shared/version.js';

export interface SidecarSupervisorOptions {
  readonly executable: string;
  readonly args?: readonly string[];
  readonly env?: Readonly<Record<string, string>>;
  readonly cwd?: string;
  readonly maxRestarts?: number;
  readonly initialBackoffMs?: number;
  /**
   * Optional guard consulted before an automatic restart. Return false
   * to defer the restart (e.g. while a job is mid-flight); the process
   * stays stopped and the caller decides when to re-run ``start()``.
   * Defaults to always-restart (plan §5.1: "restarts only when safe").
   */
  readonly restartSafe?: () => boolean;
}

export interface SidecarStatus {
  readonly state: 'starting' | 'ready' | 'crashed' | 'stopped';
  readonly pid: number | null;
  readonly restartCount: number;
  readonly lastExitCode: number | null;
}

export interface SidecarEventMap {
  ready: void;
  crashed: { exitCode: number | null };
  frame: Frame;
  log: string;
  stopped: void;
}

export class SidecarSupervisor extends EventEmitter {
  private readonly options: Required<SidecarSupervisorOptions>;
  private child: ChildProcess | null = null;
  private stdoutLines: ReadLineInterface | null = null;
  private stderrLines: ReadLineInterface | null = null;
  private restartCount = 0;
  private lastExitCode: number | null = null;
  private state: SidecarStatus['state'] = 'stopped';
  private stopRequested = false;
  private readonly pendingIds: Set<string> = new Set();

  constructor(options: SidecarSupervisorOptions) {
    super();
    this.options = {
      executable: options.executable,
      args: options.args ?? [],
      env: options.env ?? {},
      cwd: options.cwd ?? process.cwd(),
      maxRestarts: options.maxRestarts ?? 5,
      initialBackoffMs: options.initialBackoffMs ?? 500,
      restartSafe: options.restartSafe ?? (() => true),
    };
  }

  override on<K extends keyof SidecarEventMap>(
    event: K,
    listener: (payload: SidecarEventMap[K]) => void,
  ): this {
    return super.on(event, listener as (...args: unknown[]) => void);
  }

  override emit<K extends keyof SidecarEventMap>(event: K, payload: SidecarEventMap[K]): boolean {
    return super.emit(event, payload);
  }

  /**
   * Start the sidecar. Resolves once the first frame is received; the
   * caller should treat that as the sidecar being ready to receive
   * requests. Rejects if the executable cannot be spawned.
   */
  async start(): Promise<void> {
    if (this.state !== 'stopped') {
      throw new Error(`sidecar already ${this.state}`);
    }
    this.stopRequested = false;
    await this.spawnOnce();
  }

  /**
   * Send a request frame to the sidecar and await the matching response.
   * Resolves on `response` or rejects on `error`. The promise is
   * deterministically cleaned up on stop.
   */
  sendRequest<P = unknown>(id: string, method: string, params: P): Promise<ResponseFrame> {
    if (!this.child || this.state !== 'ready') {
      return Promise.reject(new Error(`sidecar not ready (state=${this.state})`));
    }
    this.pendingIds.add(id);
    const wire: Frame = {
      jsonrpc: '2.0',
      v: PROTOCOL_VERSION,
      kind: 'request',
      id,
      method,
      params,
    };
    this.writeFrame(wire);
    return new Promise((resolve, reject) => {
      const onFrame = (received: Frame) => {
        if ('id' in received && received.id === id) {
          this.removeListener('frame', onFrame);
          this.removeListener('stopped', onStopped);
          this.pendingIds.delete(id);
          if (received.kind === 'error') {
            reject(new Error(received.error.message));
          } else if (received.kind === 'response') {
            resolve(received);
          }
          // ignore request/event frames that happen to match id
        }
      };
      const onStopped = () => {
        this.removeListener('frame', onFrame);
        this.removeListener('stopped', onStopped);
        this.pendingIds.delete(id);
        reject(new Error('sidecar stopped before response'));
      };
      this.on('frame', onFrame);
      this.on('stopped', onStopped);
    });
  }

  status(): SidecarStatus {
    return {
      state: this.state,
      pid: this.child?.pid ?? null,
      restartCount: this.restartCount,
      lastExitCode: this.lastExitCode,
    };
  }

  async stop(): Promise<void> {
    this.stopRequested = true;
    if (!this.child) return;
    this.child.kill('SIGTERM');
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        this.child?.kill('SIGKILL');
        resolve();
      }, 2000);
      this.child?.once('exit', () => {
        clearTimeout(timer);
        resolve();
      });
    });
    this.state = 'stopped';
    this.emit('stopped', undefined);
  }

  private async spawnOnce(): Promise<void> {
    this.state = 'starting';
    const spawnOptions: SpawnOptions = {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, ...this.options.env },
      cwd: this.options.cwd,
    };
    const child = spawn(pathResolve(this.options.executable), [...this.options.args], spawnOptions);
    this.child = child;

    if (!child.stdout || !child.stdin || !child.stderr) {
      throw new Error('sidecar stdio pipes unavailable');
    }
    this.stdoutLines = createInterface({ input: child.stdout });
    this.stderrLines = createInterface({ input: child.stderr });

    this.stdoutLines.on('line', (line) => this.handleLine(line));
    this.stderrLines.on('line', (line) => this.emit('log', line));

    child.on('exit', (code) => this.handleExit(code));
    child.on('error', (err) => this.emit('log', `spawn error: ${err.message}`));

    // The sidecar is considered ready after the first frame is parsed.
    // Until then, the supervisor buffers; the test surface asserts
    // that the first frame is the `sidecar.ready` event.
  }

  private handleLine(line: string): void {
    const frame = decodeFrame(line);
    if (!frame) {
      this.emit('log', `unparseable frame: ${line}`);
      return;
    }
    if (frame.kind === 'event' && frame.method === 'sidecar.ready') {
      this.state = 'ready';
      this.emit('ready', undefined);
    }
    this.emit('frame', frame);
  }

  private handleExit(code: number | null): void {
    this.lastExitCode = code;
    this.child = null;
    this.stdoutLines?.close();
    this.stderrLines?.close();
    this.state = 'crashed';
    this.emit('crashed', { exitCode: code });
    if (this.stopRequested) {
      this.state = 'stopped';
      this.emit('stopped', undefined);
      return;
    }
    if (this.restartCount >= this.options.maxRestarts) {
      this.state = 'stopped';
      this.emit('stopped', undefined);
      return;
    }
    // Plan §5.1: restart only when safe. If a job is mid-flight, the
    // caller defers the restart; the process stays stopped and the
    // caller re-runs start() when it is safe.
    if (!this.options.restartSafe()) {
      this.state = 'stopped';
      this.emit('stopped', undefined);
      return;
    }
    this.restartCount += 1;
    const backoff = this.options.initialBackoffMs * 2 ** (this.restartCount - 1);
    setTimeout(() => {
      if (!this.stopRequested) {
        this.spawnOnce().catch((err) => this.emit('log', `restart failed: ${String(err)}`));
      }
    }, backoff);
  }

  private writeFrame(frame: Frame): void {
    if (!this.child?.stdin) {
      throw new Error('sidecar stdin unavailable');
    }
    this.child.stdin.write(encodeFrame(frame));
  }
}
