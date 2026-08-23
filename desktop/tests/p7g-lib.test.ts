/**
 * Tests for the pure state-presentation logic added with #88 (workflow and
 * operational-state polish): the job state -> chip tone and job state ->
 * meter status mappings, the asset lifecycle tone, the long-path split, and
 * the outcome / policy / tool label helpers.
 *
 * These assert *mappings*, not CSS. What each tone looks like is the
 * stylesheet's business; that a `cancelled` job is not handed the same tone
 * as a `succeeded` one is this file's.
 */
import { describe, expect, it } from 'vitest';
import {
  jobErrorTone,
  jobIncomplete,
  jobMeterStatus,
  jobNoteLabel,
  jobStateTone,
} from '../renderer/src/lib/job-state.js';
import { lifecycleTally, lifecycleTone } from '../renderer/src/lib/asset.js';
import { splitPathTail } from '../renderer/src/lib/format.js';
import { outcomeTone } from '../renderer/src/lib/organize.js';
import { policyHealthLabel } from '../renderer/src/lib/projects.js';
import { toolTone } from '../renderer/src/lib/doctor.js';
import { homeCards } from '../renderer/src/lib/home.js';
import type { AssetSummary } from '../shared/ipc-methods.js';

/** Every state `application/jobs.py` can put a job in. */
const ALL_STATES = [
  'planned',
  'awaiting_review',
  'queued',
  'running',
  'verifying',
  'succeeded',
  'failed',
  'cancelled',
  'needs_attention',
  'resumable',
] as const;

describe('jobStateTone', () => {
  it('separates the three terminal outcomes', () => {
    // The defect this fixes: succeeded and cancelled both fell through to
    // the untoned chip, so a good outcome and an aborted one drew the same
    // grey plate.
    expect(jobStateTone('succeeded')).toBe('ok');
    expect(jobStateTone('cancelled')).toBe('cancelled');
    expect(jobStateTone('failed')).toBe('danger');
  });

  it('does not dress work in flight as work that succeeded', () => {
    for (const state of ['queued', 'running', 'verifying', 'resumable']) {
      expect(jobStateTone(state)).toBe('active');
    }
    expect(jobStateTone('running')).not.toBe(jobStateTone('succeeded'));
  });

  it('marks the states that are waiting on a person', () => {
    expect(jobStateTone('needs_attention')).toBe('attention');
    expect(jobStateTone('awaiting_review')).toBe('attention');
  });

  it('gives an unknown state a quiet chip rather than throwing', () => {
    expect(jobStateTone('teleported')).toBe('neutral');
    expect(jobStateTone('')).toBe('neutral');
  });

  it('assigns one of the seven known tones to every state in the lifecycle', () => {
    const tones = ['neutral', 'active', 'ok', 'warn', 'danger', 'cancelled', 'attention'];
    for (const state of ALL_STATES) {
      expect(tones).toContain(jobStateTone(state));
    }
  });
});

describe('jobMeterStatus', () => {
  it('reserves the completion treatment for a confirmed completion', () => {
    expect(jobMeterStatus('succeeded')).toBe('complete');
    for (const state of ALL_STATES) {
      if (state === 'succeeded') continue;
      expect(jobMeterStatus(state)).not.toBe('complete');
    }
  });

  it('reads a terminal-but-incomplete job as stopped, not as progress', () => {
    expect(jobMeterStatus('failed')).toBe('failed');
    expect(jobMeterStatus('cancelled')).toBe('cancelled');
    expect(jobMeterStatus('failed')).not.toBe('running');
    expect(jobMeterStatus('cancelled')).not.toBe('running');
  });

  it('does not draw a stalled job as climbing', () => {
    expect(jobMeterStatus('needs_attention')).toBe('stalled');
  });

  it('reports no progress for a job that has not started work', () => {
    expect(jobMeterStatus('planned')).toBe('idle');
    expect(jobMeterStatus('awaiting_review')).toBe('idle');
    expect(jobMeterStatus('nonsense')).toBe('idle');
  });
});

describe('jobIncomplete', () => {
  it('claims every state where work stopped short', () => {
    expect(jobIncomplete('failed')).toBe(true);
    expect(jobIncomplete('cancelled')).toBe(true);
    expect(jobIncomplete('needs_attention')).toBe(true);
  });

  it('claims neither a finished job nor a moving one', () => {
    expect(jobIncomplete('succeeded')).toBe(false);
    expect(jobIncomplete('running')).toBe(false);
    expect(jobIncomplete('planned')).toBe(false);
  });
});

describe('jobErrorTone', () => {
  it('is only red where there is no way forward', () => {
    expect(jobErrorTone('failed')).toBe('danger');
    expect(jobErrorTone('cancelled')).toBe('warn');
    expect(jobErrorTone('needs_attention')).toBe('warn');
  });
});

describe('jobNoteLabel', () => {
  it('names what happened rather than restating the severity', () => {
    expect(jobNoteLabel('failed')).toBe('Failed');
    expect(jobNoteLabel('cancelled')).toBe('Cancelled');
    expect(jobNoteLabel('needs_attention')).toBe('Held');
  });

  it('does not call a cancelled run held', () => {
    expect(jobNoteLabel('cancelled')).not.toBe(jobNoteLabel('needs_attention'));
  });
});

describe('lifecycleTone', () => {
  it('makes a missing replica the loudest state on the screen', () => {
    expect(lifecycleTone('missing')).toBe('danger');
    expect(lifecycleTone('missing')).not.toBe(lifecycleTone('verified'));
  });

  it('keeps copied and verified apart', () => {
    // A copied-but-unverified file means the source card is still the only
    // confirmed copy, which is the opposite of the reassurance `ok` gives.
    expect(lifecycleTone('copied')).toBe('warn');
    expect(lifecycleTone('verified')).toBe('ok');
  });

  it('flags needs_review as waiting on a person', () => {
    expect(lifecycleTone('needs_review')).toBe('attention');
  });

  it('leaves discovered and unknown states quiet', () => {
    expect(lifecycleTone('discovered')).toBe('neutral');
    expect(lifecycleTone('something_new')).toBe('neutral');
  });
});

describe('lifecycleTally', () => {
  const asset = (lifecycleState: string): AssetSummary => ({
    id: `a${lifecycleState}`,
    sourceId: 1,
    sourceRelativePath: `${lifecycleState}.mxf`,
    observedSize: 1,
    observedMtime: 1,
    lifecycleState,
    mediaKind: 'video',
    firstSeenAt: '2026-08-01T00:00:00Z',
  });

  it('counts only the states that need a human', () => {
    const tally = lifecycleTally([
      asset('verified'),
      asset('verified'),
      asset('missing'),
      asset('needs_review'),
      asset('copied'),
      asset('discovered'),
    ]);
    expect(tally).toEqual({ missing: 1, needsReview: 1, unverified: 1 });
  });

  it('is all zeroes for an empty or healthy library', () => {
    expect(lifecycleTally([])).toEqual({ missing: 0, needsReview: 0, unverified: 0 });
    expect(lifecycleTally([asset('verified')])).toEqual({
      missing: 0,
      needsReview: 0,
      unverified: 0,
    });
  });
});

describe('splitPathTail', () => {
  it('keeps the leaf whole and hands the rest to the head', () => {
    expect(splitPathTail('/Volumes/Sable-Work/harbour/A014C0031.mxf')).toEqual({
      head: '/Volumes/Sable-Work/harbour/',
      tail: 'A014C0031.mxf',
    });
  });

  it('rejoins to exactly the input, separator and all', () => {
    for (const path of [
      '/Volumes/A/B/c.mxf',
      'relative/dir/file.mov',
      'bare.mxf',
      '/',
      '/Volumes/trailing/',
      'C:\\Media\\DAY_01\\A001.mxf',
    ]) {
      const { head, tail } = splitPathTail(path);
      expect(head + tail).toBe(path);
    }
  });

  it('leaves a bare name entirely in the tail, so nothing is hidden', () => {
    expect(splitPathTail('A014C0031.mxf')).toEqual({ head: '', tail: 'A014C0031.mxf' });
    expect(splitPathTail('')).toEqual({ head: '', tail: '' });
  });

  it('splits a Windows path on its own separator', () => {
    expect(splitPathTail('C:\\Media\\DAY_01\\A001.mxf')).toEqual({
      head: 'C:\\Media\\DAY_01\\',
      tail: 'A001.mxf',
    });
  });

  it('treats a trailing separator as a head with no leaf', () => {
    expect(splitPathTail('/Volumes/Sable-Work/')).toEqual({
      head: '/Volumes/Sable-Work/',
      tail: '',
    });
  });
});

describe('outcomeTone', () => {
  it('is a failure when nothing landed at all', () => {
    expect(outcomeTone({ ok: 0, failed: 12, total: 12 })).toBe('danger');
  });

  it('is a warning when some landed and some did not', () => {
    expect(outcomeTone({ ok: 411, failed: 1, total: 412 })).toBe('warn');
  });

  it('is a success only when nothing failed', () => {
    expect(outcomeTone({ ok: 412, failed: 0, total: 412 })).toBe('ok');
    expect(outcomeTone({ ok: 0, failed: 0, total: 0 })).toBe('ok');
  });
});

describe('policyHealthLabel', () => {
  it('names the finding rather than the severity', () => {
    expect(policyHealthLabel('danger')).toBe('no backup root');
    expect(policyHealthLabel('warn')).toBe('unverified');
    expect(policyHealthLabel('ok')).toBe('policy met');
  });
});

describe('toolTone', () => {
  it('treats Resolve as optional however the sidecar spells it', () => {
    // The sidecar reports the tool as an operator knows it, so an exact
    // `=== 'resolve'` test never fired and a missing optional integration
    // was drawn in danger red.
    expect(toolTone('DaVinci Resolve', false)).toBe('attention');
    expect(toolTone('resolve', false)).toBe('attention');
  });

  it('keeps a missing required tool in danger', () => {
    expect(toolTone('ffmpeg', false)).toBe('danger');
    expect(toolTone('ffprobe', false)).toBe('danger');
  });

  it('is ok whenever the tool is present', () => {
    expect(toolTone('ffmpeg', true)).toBe('ok');
    expect(toolTone('DaVinci Resolve', true)).toBe('ok');
  });
});

describe('homeCards', () => {
  const summary = {
    activeJobs: 1,
    attentionJobs: 0,
    failedJobs: 0,
    unsafeCards: 0,
    unverifiedReplicas: 0,
    assets: 0,
    proxyPending: 0,
  };

  it('gives active work the accent tone, not the success tone', () => {
    const active = homeCards(summary).find((c) => c.label === 'Active jobs');
    expect(active?.tone).toBe('active');
  });

  it('keeps the failure tones where they were', () => {
    const cards = homeCards(summary);
    expect(cards.find((c) => c.label === 'Failed')?.tone).toBe('danger');
    expect(cards.find((c) => c.label === 'Needs attention')?.tone).toBe('attention');
    expect(cards.find((c) => c.label === 'Unverified replicas')?.tone).toBe('warn');
  });
});
