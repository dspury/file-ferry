/**
 * Tests for the pure logic changed by the fold-and-density pass (#89-#91).
 *
 * `tallyNotice` collapses Media's three lifecycle banners into one, which
 * makes it the single place the safety copy above the table now lives. The
 * tests that matter are the ones that would notice a fact going missing in
 * the collapse: both hardware instructions the three banners carried,
 * appearing exactly when their condition is present, and — the one the
 * issue's own draft wording got wrong — every search term the banner offers
 * actually listing the assets it says it will. The draft told the operator to
 * search `unverified`, which is the screen's word for the group and matches
 * no row: `searchAssets` matches on `lifecycleState`, and that state is
 * `copied`.
 */
import { describe, expect, it } from 'vitest';
import { lifecycleTally, searchAssets, tallyNotice } from '../renderer/src/lib/asset.js';
import type { AssetSummary } from '../shared/ipc-methods.js';

function asset(id: number, lifecycleState: string): AssetSummary {
  return {
    id: `ast_${id}`,
    sourceId: 1,
    sourceRelativePath: `PRIVATE/M4ROOT/CLIP/A014C${String(id).padStart(4, '0')}.mxf`,
    observedSize: 1024,
    observedMtime: 1786000000 + id,
    lifecycleState,
    mediaKind: 'video',
    firstSeenAt: '2026-08-14T18:03:00Z',
  };
}

/** Three missing, one needing review, two copied-not-verified, four clean. */
const LIBRARY: AssetSummary[] = [
  asset(1, 'missing'),
  asset(2, 'missing'),
  asset(3, 'missing'),
  asset(4, 'needs_review'),
  asset(5, 'copied'),
  asset(6, 'copied'),
  asset(7, 'verified'),
  asset(8, 'verified'),
  asset(9, 'verified'),
  asset(10, 'verified'),
];

describe('tallyNotice', () => {
  it('says nothing at all about a clean library', () => {
    expect(tallyNotice({ missing: 0, needsReview: 0, unverified: 0 })).toBeNull();
    expect(tallyNotice(lifecycleTally([asset(1, 'verified')]))).toBeNull();
  });

  it('takes the worst severity present, not one per tally', () => {
    expect(tallyNotice({ missing: 1, needsReview: 9, unverified: 9 })?.tone).toBe('danger');
    expect(tallyNotice({ missing: 0, needsReview: 1, unverified: 0 })?.tone).toBe('warn');
    expect(tallyNotice({ missing: 0, needsReview: 0, unverified: 1 })?.tone).toBe('warn');
  });

  it('keeps every non-zero count, worst first, and drops the zeroes', () => {
    const notice = tallyNotice(lifecycleTally(LIBRARY));
    expect(notice?.counts).toEqual([
      '3 assets ferry can no longer find on disk',
      '1 asset could not be classified automatically',
      '2 assets copied but not yet verified',
    ]);
    expect(tallyNotice({ missing: 0, needsReview: 0, unverified: 4 })?.counts).toEqual([
      '4 assets copied but not yet verified',
    ]);
  });

  it('agrees with itself about singulars', () => {
    const one = tallyNotice({ missing: 1, needsReview: 1, unverified: 1 });
    expect(one?.counts).toEqual([
      '1 asset ferry can no longer find on disk',
      '1 asset could not be classified automatically',
      '1 asset copied but not yet verified',
    ]);
  });

  it('keeps both safety instructions the three banners carried, worst first', () => {
    // The stacked banners said two separate things about hardware: do not
    // format the card a missing asset came from, and an unverified copy
    // leaves the source as the only confirmed one. Both have to survive the
    // collapse, and a library in both conditions gets both.
    expect(tallyNotice({ missing: 3, needsReview: 1, unverified: 2 })?.safety).toEqual([
      'Do not format or erase the source a missing asset came from.',
      'Until a copy is verified, the source is the only confirmed copy.',
    ]);
    expect(tallyNotice({ missing: 1, needsReview: 0, unverified: 0 })?.safety).toEqual([
      'Do not format or erase the source a missing asset came from.',
    ]);
    expect(tallyNotice({ missing: 0, needsReview: 0, unverified: 1 })?.safety).toEqual([
      'Until a copy is verified, the source is the only confirmed copy.',
    ]);
  });

  it('says nothing about hardware when no counted group is about hardware', () => {
    // needs_review is a classification queue: nothing is at risk of being
    // erased, so an instruction not to format a card would be an alarm
    // about a condition that is not present.
    expect(tallyNotice({ missing: 0, needsReview: 5, unverified: 0 })?.safety).toEqual([]);
  });

  it('offers one search term per counted group, in the same order', () => {
    expect(tallyNotice(lifecycleTally(LIBRARY))?.terms).toEqual([
      'missing',
      'needs_review',
      'copied',
    ]);
    expect(tallyNotice({ missing: 0, needsReview: 2, unverified: 0 })?.terms).toEqual([
      'needs_review',
    ]);
  });

  it('offers only search terms that really list the assets it counted', () => {
    const notice = tallyNotice(lifecycleTally(LIBRARY));
    expect(notice).not.toBeNull();
    const found = (notice?.terms ?? []).map((term) => searchAssets(LIBRARY, term).length);
    // The banner promises "search X to list them"; the counts it printed and
    // the rows that search returns have to be the same number, or the
    // instruction sends the operator to an empty table.
    expect(found).toEqual([3, 1, 2]);
    expect(searchAssets(LIBRARY, 'unverified')).toHaveLength(0);
  });
});
