/**
 * Tests for the pure accessibility logic introduced with the Rams design
 * review fixes (issues #64–#69): the modal focus-trap arithmetic and the
 * ARIA progress-value clamp. These run in node without React/DOM.
 *
 * Extended by the #95 accessibility-tree pass with `jobRowLabel`, and with
 * the `splitPathTail` shapes that pass rendered for the first time.
 */
import { describe, expect, it } from 'vitest';
import { nextFocusIndex, isTrapKey, FOCUSABLE_SELECTOR } from '../renderer/src/lib/focus-trap.js';
import { jobRowLabel, progressPercent } from '../renderer/src/lib/activity.js';
import { splitPathTail } from '../renderer/src/lib/format.js';
import type { JobDetail } from '../shared/ipc-methods.js';

describe('nextFocusIndex', () => {
  it('wraps forward off the last element', () => {
    expect(nextFocusIndex(2, 3, false)).toBe(0);
  });

  it('wraps backward off the first element', () => {
    expect(nextFocusIndex(0, 3, true)).toBe(2);
  });

  it('defers to the browser in the middle of the range', () => {
    expect(nextFocusIndex(1, 3, false)).toBeNull();
    expect(nextFocusIndex(1, 3, true)).toBeNull();
  });

  it('pulls focus back in when it is outside the trap', () => {
    expect(nextFocusIndex(-1, 3, false)).toBe(0);
    expect(nextFocusIndex(-1, 3, true)).toBe(2);
  });

  it('pins a single focusable element in both directions', () => {
    expect(nextFocusIndex(0, 1, false)).toBe(0);
    expect(nextFocusIndex(0, 1, true)).toBe(0);
  });

  it('does nothing when the dialog has nothing focusable', () => {
    expect(nextFocusIndex(-1, 0, false)).toBeNull();
    expect(nextFocusIndex(0, 0, true)).toBeNull();
  });
});

describe('FOCUSABLE_SELECTOR', () => {
  it('skips disabled controls', () => {
    expect(FOCUSABLE_SELECTOR).toContain('button:not([disabled])');
  });

  it('excludes tabindex="-1", which Tab cannot reach', () => {
    expect(FOCUSABLE_SELECTOR).toContain('[tabindex]:not([tabindex="-1"])');
  });
});

describe('isTrapKey', () => {
  it('claims Tab and nothing else', () => {
    expect(isTrapKey('Tab')).toBe(true);
    expect(isTrapKey('Escape')).toBe(false);
    expect(isTrapKey('a')).toBe(false);
  });
});

describe('progressPercent', () => {
  it('converts a fraction to a whole percentage', () => {
    expect(progressPercent(0)).toBe(0);
    expect(progressPercent(0.5)).toBe(50);
    expect(progressPercent(1)).toBe(100);
  });

  it('rounds to an integer, as aria-valuenow expects', () => {
    expect(progressPercent(1 / 3)).toBe(33);
  });

  it('clamps out-of-range input so aria-valuenow stays within min/max', () => {
    expect(progressPercent(-1)).toBe(0);
    expect(progressPercent(2)).toBe(100);
  });

  it('treats a non-finite fraction as zero rather than emitting NaN', () => {
    expect(progressPercent(Number.NaN)).toBe(0);
    expect(progressPercent(Number.POSITIVE_INFINITY)).toBe(100);
    expect(progressPercent(Number.NEGATIVE_INFINITY)).toBe(0);
  });
});

/*
 * A row's controls are only unambiguous inside the table, where the Command
 * and State cells are announced first. Pulled into a controls list they were
 * four buttons called "Cancel", so the name has to carry the row's identity.
 */
describe('jobRowLabel', () => {
  const RUNNING_OFFLOAD: JobDetail = {
    id: 'job_9f21',
    projectId: 'prj_7ac1',
    sessionId: null,
    command: 'offload',
    state: 'running',
    currentStep: 'copy',
    totalSteps: 4,
    startedAt: '2026-08-22T22:51:00Z',
    updatedAt: '2026-08-22T23:04:00Z',
    finishedAt: null,
    error: null,
    resumable: true,
  };
  const job = (over: Partial<JobDetail> = {}): JobDetail => ({ ...RUNNING_OFFLOAD, ...over });

  it('leads with the visible label, as WCAG 2.5.3 requires', () => {
    expect(jobRowLabel('Cancel', job())).toMatch(/^Cancel /);
    expect(jobRowLabel('Receipt', job())).toMatch(/^Receipt /);
  });

  it('names the command and the id, so two rows never collide', () => {
    expect(jobRowLabel('Cancel', job())).toBe('Cancel offload job_9f21');
  });

  it('separates two jobs running the same command, which is the normal case', () => {
    const a = jobRowLabel('Cancel', job({ id: 'job_1111' }));
    const b = jobRowLabel('Cancel', job({ id: 'job_2222' }));
    expect(a).not.toBe(b);
  });

  it('is the same shape for the meter, so a row reads consistently', () => {
    expect(jobRowLabel('Progress for', job())).toBe('Progress for offload job_9f21');
  });
});

/*
 * Windows shapes. #95 rendered these through PathCell/PathText for the first
 * time and confirmed the leaf survives truncation and no character is
 * reordered; these lock the split itself, which is the part that is pure.
 */
describe('splitPathTail on Windows shapes', () => {
  it('splits a UNC path on the share-relative separator', () => {
    expect(splitPathTail('\\\\server\\share\\footage\\A014.mxf')).toEqual({
      head: '\\\\server\\share\\footage\\',
      tail: 'A014.mxf',
    });
  });

  it('keeps the leaf out of a long-path prefix, however deep the run', () => {
    const path = '\\\\?\\C:\\very\\long\\path\\A014C0031_260814_R1XZ.mxf';
    expect(splitPathTail(path)).toEqual({
      head: '\\\\?\\C:\\very\\long\\path\\',
      tail: 'A014C0031_260814_R1XZ.mxf',
    });
  });

  it('treats a drive root as a head with no leaf', () => {
    expect(splitPathTail('C:\\')).toEqual({ head: 'C:\\', tail: '' });
    expect(splitPathTail('E:\\')).toEqual({ head: 'E:\\', tail: '' });
  });

  it('leaves a share root split at the share name', () => {
    expect(splitPathTail('\\\\server\\share')).toEqual({
      head: '\\\\server\\',
      tail: 'share',
    });
  });

  it('rejoins every Windows shape to exactly the input', () => {
    for (const path of [
      'C:\\Users\\op\\Footage\\A014.mxf',
      '\\\\server\\share\\footage\\A014.mxf',
      '\\\\?\\C:\\very\\long\\path\\A014.mxf',
      'D:\\Footage\\Day014\\',
      'C:\\',
      'A014.mxf',
    ]) {
      const { head, tail } = splitPathTail(path);
      expect(head + tail).toBe(path);
    }
  });
});
