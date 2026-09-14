/**
 * The Organize screen must not offer to organize a source it cannot
 * account for (destination-presets spec §6.3, §7.1; review revision R08).
 *
 * `source.inspect` surfacing an `errorCount` did not, by itself, stop
 * anything: the screen forwarded `inspected.entries` straight into
 * preview and apply, so an unreadable subtree produced a green
 * "complete" run for a partial transfer. The backend now refuses these
 * too — that refusal is the real guarantee — and this gate is what
 * tells the user before they press the button.
 */
import { describe, expect, it } from 'vitest';
import { sourceScanBlocker } from '../renderer/src/lib/organize.js';
import type { SourceInspectResult } from '../shared/ipc-methods.js';

function inspected(over: Partial<SourceInspectResult> = {}): SourceInspectResult {
  return {
    sourceId: 1,
    rootPath: '/src',
    kind: 'existing_media',
    label: null,
    fileCount: 2,
    totalBytes: 10,
    manifestHash: 'h',
    entries: [
      { path: 'a.mov', size: 5, mtime: 1 },
      { path: 'b.mov', size: 5, mtime: 1 },
    ],
    ...over,
  };
}

describe('sourceScanBlocker', () => {
  it('allows a source that scanned cleanly', () => {
    expect(sourceScanBlocker(inspected())).toBeNull();
    // Explicit zero/empty findings are as clean as absent ones.
    expect(sourceScanBlocker(inspected({ errorCount: 0, nonFiles: [] }))).toBeNull();
  });

  it('blocks when entries could not be read, and names them', () => {
    const blocker = sourceScanBlocker(
      inspected({ errorCount: 2, scanErrors: ['locked/deep.mov: lstat failed'] }),
    );
    expect(blocker).not.toBeNull();
    expect(blocker).toContain('2 items');
    expect(blocker).toContain('locked/deep.mov');
  });

  it('blocks on symlinks inside the folder, naming them', () => {
    const blocker = sourceScanBlocker(
      inspected({ nonFiles: [{ path: 'DCIM/link.mov', size: 0, mtime: 0, entryType: 'symlink' }] }),
    );
    expect(blocker).not.toBeNull();
    expect(blocker).toContain('1 symlink inside this folder');
    expect(blocker).toContain('DCIM/link.mov');
    // The restriction is about links *within* the tree; picking a folder
    // that is itself a drive alias is ordinary and must not read as banned.
    expect(blocker).toContain('alias for a drive is fine');
  });

  it('describes mixed special objects without calling them all symlinks', () => {
    const blocker = sourceScanBlocker(
      inspected({
        nonFiles: [
          { path: 'link.mov', size: 0, mtime: 0, entryType: 'symlink' },
          { path: 'pipe', size: 0, mtime: 0, entryType: 'other' },
        ],
      }),
    );
    expect(blocker).toContain('2 items here are not regular files');
  });

  it('does not block before a source has been inspected', () => {
    expect(sourceScanBlocker(null)).toBeNull();
  });
});
