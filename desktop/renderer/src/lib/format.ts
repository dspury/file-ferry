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
