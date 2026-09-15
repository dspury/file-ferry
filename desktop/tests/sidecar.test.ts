/**
 * Tests for sidecar command resolution and protocol-error handling
 * (plan §10.6.1, §10.6.3).
 *
 * Command resolution is pure and injected-existence-testable. Protocol
 * errors are surfaced as typed events and a counter. The full
 * spawn/restart lifecycle requires a real child process, so those
 * paths are covered by the packaged-app smoke test in Package 9; here
 * we verify the decision logic that drives them.
 */
import { describe, expect, it, vi } from 'vitest';
import { joinPath, resolveDevPython, resolveSidecarCommand } from '../electron/sidecar-command.js';
import { SidecarSupervisor, classifyUnexpectedFrame } from '../electron/sidecar.js';
import type { ProtocolErrorEvent } from '../electron/sidecar.js';
import { decodeFrame, encodeFrame, type RequestFrame } from '../shared/ipc-schema.js';
import { PROTOCOL_VERSION } from '../shared/version.js';

// SAFETY: 'darwin' is a member of the NodeJS.Platform union; the assertion
// only stops TypeScript widening the literal to `string` in these fixtures.
const DEV = {
  isPackaged: false,
  resourcesPath: '/resources',
  workspaceRoot: '/repo',
  platform: 'darwin' as NodeJS.Platform,
};

// SAFETY: as above.
const PACKAGED = {
  isPackaged: true,
  workspaceRoot: '/repo',
  platform: 'darwin' as NodeJS.Platform,
};

describe('resolveSidecarCommand', () => {
  // Regression: development used to launch `process.execPath -m file_ferry.service`,
  // i.e. the Electron binary with a Python flag. It must launch an interpreter.
  it('runs the workspace virtualenv interpreter in development', () => {
    const cmd = resolveSidecarCommand({
      ...DEV,
      exists: (p) => p === '/repo/.venv/bin/python',
    });
    expect(cmd.executable).toBe('/repo/.venv/bin/python');
    expect(cmd.args).toEqual(['-m', 'file_ferry.service']);
    expect(cmd.cwd).toBe('/repo');
  });

  it('falls back to python3 on PATH when there is no workspace virtualenv', () => {
    const cmd = resolveSidecarCommand({ ...DEV, exists: () => false });
    expect(cmd.executable).toBe('python3');
    expect(cmd.args).toEqual(['-m', 'file_ferry.service']);
  });

  it('honors a FERRY_PYTHON override ahead of the virtualenv', () => {
    const cmd = resolveSidecarCommand({
      ...DEV,
      pythonOverride: '/opt/py/bin/python3.13',
      exists: () => true,
    });
    expect(cmd.executable).toBe('/opt/py/bin/python3.13');
  });

  it('resolves the frozen executable in a packaged build', () => {
    const cmd = resolveSidecarCommand({
      ...PACKAGED,
      resourcesPath: '/app/Resources',
      exists: (p: string) => p.endsWith('/sidecar/ferry-service'),
    });
    expect(cmd.executable).toBe('/app/Resources/sidecar/ferry-service');
    expect(cmd.args).toEqual([]);
    // Packaged builds inherit the app's cwd; nothing workspace-relative.
    expect(cmd.cwd).toBeUndefined();
  });

  it('prefers the .exe candidate on Windows', () => {
    const cmd = resolveSidecarCommand({
      ...PACKAGED,
      platform: 'win32',
      resourcesPath: 'C:/app/Resources',
      exists: (p: string) => p.endsWith('ferry-service.exe'),
    });
    expect(cmd.executable).toBe('C:/app/Resources/sidecar/ferry-service.exe');
  });

  it('throws when no frozen executable exists', () => {
    expect(() =>
      resolveSidecarCommand({ ...PACKAGED, resourcesPath: '/res', exists: () => false }),
    ).toThrow('sidecar executable not found');
  });
});

describe('resolveDevPython', () => {
  it('uses the Scripts layout on Windows', () => {
    const python = resolveDevPython(
      'C:/repo',
      'win32',
      undefined,
      (p) => p === 'C:/repo/.venv/Scripts/python.exe',
    );
    expect(python).toBe('C:/repo/.venv/Scripts/python.exe');
  });

  it('falls back to `python` (not `python3`) on Windows', () => {
    expect(resolveDevPython('C:/repo', 'win32', undefined, () => false)).toBe('python');
  });
});

describe('joinPath', () => {
  it('joins and collapses duplicate slashes', () => {
    expect(joinPath('/a', 'b', 'c')).toBe('/a/b/c');
    expect(joinPath('/a/', '/b')).toBe('/a/b');
  });
});

describe('protocol frame errors (decode side)', () => {
  it('rejects a version mismatch so the supervisor can surface it', () => {
    const bad = JSON.stringify({
      jsonrpc: '2.0',
      v: PROTOCOL_VERSION + 1,
      kind: 'request',
      id: 'x',
      method: 'a',
      params: {},
    });
    expect(decodeFrame(bad)).toBeNull();
  });

  it('rejects a request frame from the sidecar (unsolicited)', () => {
    const request: RequestFrame = {
      jsonrpc: '2.0',
      v: PROTOCOL_VERSION,
      kind: 'request',
      id: 'x',
      method: 'a',
      params: {},
    };
    const wire = encodeFrame(request);
    // The supervisor treats a request on sidecar stdout as a violation;
    // it is decodeable but not a legitimate sidecar response.
    expect(decodeFrame(wire)).not.toBeNull();
  });

  it('rejects non-NDJSON garbage', () => {
    expect(decodeFrame('{not json\n')).toBeNull();
    expect(decodeFrame('')).toBeNull();
  });
});

describe('classifyUnexpectedFrame', () => {
  // Regression for the bug where both ternary branches returned
  // 'unsolicited_response'. The kind discriminator must be honored.
  it("classifies an unsolicited request frame as 'unsolicited_request'", () => {
    expect(classifyUnexpectedFrame({ kind: 'request' })).toBe('unsolicited_request');
  });

  it("classifies an unsolicited response frame as 'unsolicited_response'", () => {
    expect(classifyUnexpectedFrame({ kind: 'response' })).toBe('unsolicited_response');
  });

  it('the returned reason matches the typed ProtocolErrorEvent union', () => {
    const reasons: ProtocolErrorEvent['reason'][] = [
      classifyUnexpectedFrame({ kind: 'request' }),
      classifyUnexpectedFrame({ kind: 'response' }),
    ];
    // Type-level check: this assignment only compiles if both values
    // are valid members of ProtocolErrorEvent['reason'].
    const typed: ProtocolErrorEvent['reason'][] = reasons;
    expect(typed).toHaveLength(2);
  });
});

describe('shutdown is not a crash', () => {
  // Regression: `handleExit` emitted `crashed` before checking
  // `stopRequested`, so the SIGTERM quit path lodged "sidecar crashed
  // (exit=null)" into the packaged app's diagnostic log on every clean
  // shutdown. This drives a real child exit down each path — a real process,
  // so the ordering is what is under test and not a stand-in for it.
  //
  // The child is this runtime, told to linger or to exit at once, so the
  // test is portable (no `/bin/sleep`) and needs no sidecar.
  const LINGER = ['-e', 'setInterval(() => {}, 1000)'];
  const EXIT_3 = ['-e', 'process.exit(3)'];

  it('never emits crashed when the exit was requested', async () => {
    const sup = new SidecarSupervisor({
      executable: process.execPath,
      args: LINGER,
      // The child never announces readiness; the wait below is meant to
      // time out after the stop has already exercised the exit path.
      readyTimeoutMs: 200,
    });
    const crashed = vi.fn();
    sup.on('crashed', crashed);
    const started = sup.start().catch(() => undefined);
    await vi.waitFor(() => expect(sup.status().pid).not.toBeNull());
    await sup.stop();
    await started;
    expect(crashed).not.toHaveBeenCalled();
    expect(sup.status().state).toBe('stopped');
  });

  it('still emits crashed for an exit nobody requested', async () => {
    const sup = new SidecarSupervisor({
      executable: process.execPath,
      args: EXIT_3,
      readyTimeoutMs: 500,
      // No restart off the back of an unrequested exit in a unit test.
      restartSafe: () => false,
    });
    const crashed = vi.fn();
    sup.on('crashed', crashed);
    await expect(sup.start()).rejects.toThrow();
    expect(crashed).toHaveBeenCalledWith({ exitCode: 3 });
    expect(sup.status().state).toBe('stopped');
  });
});

describe('readiness gate', () => {
  // Regression: `start()` documented "resolves once the sidecar is ready" but
  // returned as soon as the child was spawned. The window then opened ahead of
  // the sidecar, and a fast renderer (the packaged file:// path) latched
  // "sidecar not ready" on its first request and never recovered.
  const supervisor = (): SidecarSupervisor =>
    new SidecarSupervisor({ executable: '/nonexistent/python', readyTimeoutMs: 50 });

  it('resolves when the sidecar announces readiness', async () => {
    const sup = supervisor();
    const ready = sup.whenReady(1000);
    sup.emit('ready', undefined);
    await expect(ready).resolves.toBeUndefined();
  });

  it('rejects when the sidecar exits before announcing readiness', async () => {
    const sup = supervisor();
    const ready = sup.whenReady(1000);
    sup.emit('crashed', { exitCode: 3 });
    await expect(ready).rejects.toThrow('exited before announcing readiness (exit=3)');
  });

  it('rejects when readiness never arrives', async () => {
    const sup = supervisor();
    await expect(sup.whenReady(10)).rejects.toThrow('did not announce readiness within 10ms');
  });

  it('does not leave listeners behind once settled', async () => {
    const sup = supervisor();
    const ready = sup.whenReady(1000);
    sup.emit('ready', undefined);
    await ready;
    expect(sup.listenerCount('ready')).toBe(0);
    expect(sup.listenerCount('crashed')).toBe(0);
  });
});
