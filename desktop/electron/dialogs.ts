/**
 * Native picker handlers owned by Electron main.
 *
 * ADR-0001: native dialogs are owned by main, exposed only through the
 * schema-validated bridge, and the renderer never supplies an arbitrary
 * path. These handlers open a native open dialog (directory or file),
 * validate the result with ``sanitizePickedPath``, and return only a
 * validated absolute path (or a cancel result) to the renderer.
 */

import { dialog, type BrowserWindow } from 'electron';
import type { PickRequest, PickResult } from '../shared/dialog.js';
import { sanitizePickedPath } from '../shared/dialog.js';

/**
 * Open a native picker and return a validated result.
 * ``parent`` is optional; when given, the dialog is modal to that window.
 */
export async function showPicker(
  parent: BrowserWindow | null,
  request: PickRequest,
): Promise<PickResult> {
  const properties: Array<'openDirectory' | 'openFile'> =
    request.kind === 'directory' ? ['openDirectory'] : ['openFile'];
  const options: Electron.OpenDialogOptions = {
    title: request.title ?? 'Choose a location',
    properties,
  };
  if (request.defaultPath !== undefined) {
    const safeDefault = sanitizePickedPath(request.defaultPath);
    if (safeDefault !== null) {
      options.defaultPath = safeDefault;
    }
  }

  const result = parent
    ? await dialog.showOpenDialog(parent, options)
    : await dialog.showOpenDialog(options);

  if (result.canceled || result.filePaths.length === 0) {
    return { path: null, cancelled: true };
  }
  const picked = sanitizePickedPath(result.filePaths[0]);
  if (picked === null) {
    return { path: null, cancelled: true };
  }
  return { path: picked, cancelled: false };
}
