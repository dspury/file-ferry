/**
 * Electron main process entry point. Owns the desktop lifecycle, the
 * single-instance lock, the sidecar supervisor, and the IPC bridge
 * to the preload script. The renderer has no role here.
 *
 * See ADR-0001 (desktop shell) and ADR-0002 (IPC protocol).
 */
import { app, BrowserWindow, ipcMain, type IpcMainInvokeEvent } from 'electron';
import { resolve as pathResolve } from 'node:path';
import { existsSync } from 'node:fs';
import { SidecarSupervisor } from './sidecar.js';
import { applyContentSecurityPolicy, baseWindowOptions } from './security.js';
import { PROTOCOL_VERSION } from '../shared/version.js';

const isDev = !app.isPackaged;

interface SidecarRequestEnvelope {
  readonly method: string;
  readonly params: unknown;
}

function resolveSidecarCommand(): { executable: string; args: string[] } {
  if (isDev) {
    return {
      executable: process.execPath,
      args: ['-m', 'media_mate.service'],
    };
  }
  const candidates = [
    pathResolve(process.resourcesPath, 'sidecar', 'media-mate-service'),
    pathResolve(process.resourcesPath, 'sidecar', 'media-mate-service.exe'),
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return { executable: candidate, args: [] };
    }
  }
  throw new Error('sidecar executable not found in packaged resources');
}

async function createMainWindow(supervisor: SidecarSupervisor): Promise<BrowserWindow> {
  const window = new BrowserWindow({
    ...baseWindowOptions(),
    width: 1280,
    height: 800,
    title: 'media-mate',
    webPreferences: {
      preload: pathResolve(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  applyContentSecurityPolicy(window.webContents.session);

  // Forward sidecar events to the renderer.
  supervisor.on('frame', (frame) => {
    if (frame.kind === 'event') {
      window.webContents.send(`sidecar:event:${frame.method}`, frame);
    }
  });

  window.once('ready-to-show', () => window.show());

  const rendererIndex = isDev
    ? 'http://localhost:5173'
    : `file://${pathResolve(__dirname, '../renderer/index.html')}`;
  await window.loadURL(rendererIndex);

  return window;
}

async function main(): Promise<void> {
  // Single-instance lock (per ADR-0001). A second launch forwards its
  // request to the existing process instead of opening a second writer.
  const gotLock = app.requestSingleInstanceLock();
  if (!gotLock) {
    app.quit();
    return;
  }

  app.on('second-instance', () => {
    // The existing process holds the lock; the new launch is a no-op.
  });

  // The desktop application does not quit when the last window closes.
  // Active jobs must continue. The user can explicitly quit via the
  // menu, the tray, or a finalize-and-quit action.
  app.on('window-all-closed', () => {
    /* keep alive */
  });

  await app.whenReady();

  const { executable, args } = resolveSidecarCommand();
  const supervisor = new SidecarSupervisor({
    executable,
    args,
    env: {
      MEDIA_MATE_PROTOCOL_VERSION: String(PROTOCOL_VERSION),
    },
  });

  supervisor.on('crashed', ({ exitCode }) => {
    console.error(`sidecar crashed (exit=${exitCode}); supervisor will restart`);
  });

  await supervisor.start();

  const mainWindow = await createMainWindow(supervisor);

  ipcMain.handle(
    'sidecar:request',
    async (_event: IpcMainInvokeEvent, envelope: SidecarRequestEnvelope) => {
      const id = crypto.randomUUID();
      const response = await supervisor.sendRequest(id, envelope.method, envelope.params);
      return response.result;
    },
  );

  void mainWindow;
}

main().catch((err) => {
  console.error('fatal:', err);
  app.exit(1);
});
