/**
 * Display formatting shared across screens.
 *
 * `formatBytes` existed verbatim in three modules (doctor, ingest, and the
 * asset detail screen). One implementation means one place to change the
 * unit convention, and the two library modules re-export it so their
 * existing callers and tests are unaffected.
 */

/** Decimal units, one decimal place — what storage vendors and NLEs show. */
export function formatBytes(n: number): string {
  if (n >= 1e12) return `${(n / 1e12).toFixed(1)} TB`;
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  return `${n} B`;
}

/** Thousands-separated count, for file tallies that reach five figures. */
export function formatCount(n: number): string {
  return n.toLocaleString();
}

/**
 * Split a path into the directory run and the leaf that identifies it.
 *
 * Long-path handling, and the fix for a real bidi defect. Path cells used
 * to truncate by setting `direction: rtl`, which keeps the *tail* visible
 * but hands the string to the bidi algorithm as an RTL paragraph: the
 * leading `/` of an absolute path is a neutral character at a paragraph
 * boundary, so it takes the paragraph direction and is drawn at the wrong
 * end — `/Volumes/Sable-Work/HarbourLights/` rendered as
 * `ork/HarbourLights/`, with a slash that is not where the path has one.
 *
 * Splitting instead means the two halves are laid out left-to-right, as
 * written, and only the head is allowed to shrink. The leaf — the filename,
 * which is what an operator is scanning for — cannot be truncated away, and
 * no character is ever moved.
 *
 * `head` keeps its trailing separator so `head + tail` is the input
 * verbatim. A path with no separator has an empty head; the callers let the
 * tail clip in that case, because there is nothing else to give up.
 */
export interface PathParts {
  /** The directory run, trailing separator included. Empty for a bare name. */
  readonly head: string;
  /** The leaf: the filename or folder name the path is about. */
  readonly tail: string;
}

export function splitPathTail(path: string): PathParts {
  // Windows paths reach the UI from a Windows install's own dialogs, and a
  // backslash separator would otherwise leave the entire path in `tail`.
  const cut = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
  if (cut < 0) return { head: '', tail: path };
  return { head: path.slice(0, cut + 1), tail: path.slice(cut + 1) };
}
