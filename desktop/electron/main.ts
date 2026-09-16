/**
 * Electron main process entry point. Owns the desktop lifecycle, the
 * single-instance lock, the sidecar supervisor, and the IPC bridge
 * to the preload script. The renderer has no role here.
 *
 * See ADR-0001 (desktop shell) and ADR-0002 (IPC protocol).
 */
import { app, BrowserWindow, ipcMain, type IpcMainInvokeEvent } from 'electron';
import { dirname, resolve as pathResolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SidecarSupervisor, type SidecarSupervisorOptions } from './sidecar.js';
import { resolveSidecarCommand } from './sidecar-command.js';
import { showPicker } from './dialogs.js';
import { ensureLogDir, appendLog, countLogFiles, openDiagnosticFolder } from './diagnostics.js';
import { applyContentSecurityPolicy, baseWindowOptions } from './security.js';
import { resolveRendererSource } from './renderer-source.js';
import {
  JobSnapshotStore,
  replayPayload,
  isJobUpdatedParams,
  jobUpdatedFrame,
} from '../shared/replay.js';
import { formatDiagnosticSummary } from '../shared/diagnostics.js';
import { PROTOCOL_VERSION } from '../shared/version.js';
import { getReleaseInfo, releaseSummary } from '../shared/release.js';
import type { PickRequest } from '../shared/dialog.js';

// The compiled main runs as an ES module (package `"type": "module"`, #138),
// where `__dirname` does not exist; this is its equivalent.
const here = dirname(fileURLToPath(import.meta.url));
interface SidecarRequestEnvelope {
  readonly method: string;
  readonly params: unknown;
}

async function createMainWindow(supervisor: SidecarSupervisor): Promise<BrowserWindow> {
  // The renderer source, resolved once: `FERRY_RENDERER_URL` can point a
  // checkout at the built renderer (#123). The CSP follows that source, not
  // packaging, so a built renderer is verified under the production policy.
  const renderer = resolveRendererSource({
    isPackaged: app.isPackaged,
    overrideUrl: process.env.FERRY_RENDERER_URL,
    distRendererPath: pathResolve(here, '../renderer/index.html'),
  });

  const window = new BrowserWindow({
    ...baseWindowOptions(),
    width: 1280,
    height: 800,
    // R-2's floor. The operator chose 600 deliberately over 900/1000, so the
    // layout has to cope down to it (see the breakpoint section in
    // styles.css) rather than the window refusing to go that narrow.
    minWidth: 600,
    minHeight: 600,
    title: 'ferry',
    webPreferences: {
      preload: pathResolve(here, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  applyContentSecurityPolicy(window.webContents.session, renderer.devServer);

  // Forward sidecar events to the renderer. Job-update events are also
  // recorded into the replay store so a reloaded window can be caught up.
  supervisor.on('frame', (frame) => {
    if (frame.kind === 'event') {
      if (frame.method === 'job.updated' && isJobUpdatedParams(frame.params)) {
        snapshotStore.record(frame.params.snapshot);
      }
      window.webContents.send(`sidecar:event:${frame.method}`, frame);
    }
  });

  // A renderer reload may lose its subscription but not job state
  // (ADR-0001). On load, replay the current job snapshots so the fresh
  // window shows live state, then it can re-subscribe for future events.
  window.webContents.on('did-finish-load', () => {
    const payload = replayPayload(snapshotStore);
    for (const snapshot of payload) {
      window.webContents.send('sidecar:event:job.updated', jobUpdatedFrame(snapshot));
    }
  });

  window.once('ready-to-show', () => window.show());

  await window.loadURL(renderer.url);

  return window;
}

// The store is module-scoped so it survives window recreation and the
// app's keep-alive-on-last-window-closed policy.
const snapshotStore = new JobSnapshotStore();

async function main(): Promise<void> {
  // Single-instance lock (per ADR-0001). A second launch forwards its
  // request to the existing process instead of opening a second writer.
  const gotLock = app.requestSingleInstanceLock();
  if (!gotLock) {
    app.quit();
    return;
  }

  app.on('second-instance', () => {
    // A second launch happened; focus and restore the existing window so
    // the user lands on the running app rather than a silent no-op.
    const win = BrowserWindow.getAllWindows()[0];
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  // The desktop application does not quit when the last window closes.
  // Active jobs must continue. The user can explicitly quit via the
  // menu, the tray, or a finalize-and-quit action.
  app.on('window-all-closed', () => {
    /* keep alive */
  });

  await app.whenReady();

  const logDir = ensureLogDir();
  const appDataDir = app.getPath('userData');
  const dbPath = pathResolve(appDataDir, 'ferry.db');
  // In development __dirname is <repo>/desktop/dist/electron, so the repo root
  // is three levels up. Packaged builds ignore it and use resourcesPath.
  const workspaceRoot = pathResolve(here, '..', '..', '..');
  const { executable, args, cwd } = resolveSidecarCommand({
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    workspaceRoot,
    platform: process.platform,
    pythonOverride: process.env.FERRY_PYTHON,
  });
  const supervisorOptions: SidecarSupervisorOptions = {
    executable,
    // The sidecar can derive these itself, but then two implementations own
    // the same paths and drift (the diagnostics panel reported a db the
    // sidecar never opened). The shell is authoritative.
    args: [...args, '--db', dbPath, '--app-data', appDataDir],
    env: {
      FERRY_PROTOCOL_VERSION: String(PROTOCOL_VERSION),
    },
  };
  // `cwd` is optional under exactOptionalPropertyTypes, so it is added only
  // when it has a value rather than passed as an explicit undefined.
  const supervisor = new SidecarSupervisor(
    cwd === undefined ? supervisorOptions : { ...supervisorOptions, cwd },
  );

  // Sidecar stderr/stdout go to the local diagnostic log (plan §8.1).
  supervisor.on('log', (line) => {
    appendLog(logDir, 'sidecar.log', line);
  });

  supervisor.on('crashed', ({ exitCode }) => {
    appendLog(logDir, 'sidecar.log', `sidecar crashed (exit=${exitCode})`);
    console.error(`sidecar crashed (exit=${exitCode}); supervisor will restart`);
  });

  // Wait for the sidecar to announce itself before showing a window, so the
  // first screen's requests land on a sidecar that can answer them. If it
  // never comes up, open the window anyway: the supervisor keeps retrying and
  // the renderer surfaces "sidecar unreachable", which beats exiting silently.
  try {
    await supervisor.start();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    appendLog(logDir, 'sidecar.log', `sidecar failed to become ready: ${message}`);
    console.error(`sidecar failed to become ready: ${message}`);
  }

  const mainWindow = await createMainWindow(supervisor);

  // Native pickers: the renderer never supplies a path; it requests a
  // picker and receives a validated result (ADR-0001).
  ipcMain.handle('dialog:pick', async (_event: IpcMainInvokeEvent, request: PickRequest) => {
    const parent = BrowserWindow.fromWebContents(_event.sender);
    return showPicker(parent, request);
  });

  // Open the local diagnostic folder.
  ipcMain.handle('app:openDiagnosticFolder', async () => {
    await openDiagnosticFolder(logDir);
    return { logDir };
  });

  // Diagnostic summary for the About/Doctor surface.
  ipcMain.handle('app:diagnostics', async () => {
    const report = {
      platform: process.platform,
      electronVersion: process.versions.electron ?? '',
      protocolVersion: PROTOCOL_VERSION,
      sidecarStatus: supervisor.status().state,
      dbPath,
      appDataDir,
      logDir,
      logCount: countLogFiles(logDir),
    };
    const summary = `${releaseSummary(getReleaseInfo())}\n` + formatDiagnosticSummary(report);
    return { summary };
  });

  ipcMain.handle(
    'sidecar:request',
    async (_event: IpcMainInvokeEvent, envelope: SidecarRequestEnvelope) => {
      const id = crypto.randomUUID();
      const response = await supervisor.sendRequest(id, envelope.method, envelope.params);
      return response.result;
    },
  );

  // Without this the Python child outlives the app: it keeps the database
  // open and accumulates one orphan per launch.
  let stopping = false;
  app.on('before-quit', (event) => {
    if (stopping) return;
    stopping = true;
    event.preventDefault();
    void supervisor.stop().finally(() => app.quit());
  });

  void mainWindow;
}

main().catch((err) => {
  console.error('fatal:', err);
  app.exit(1);
});
