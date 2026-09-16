// @vitest-environment jsdom
/**
 * Render tests (issue #122). The suite ran with no DOM, so nothing in the
 * renderer had ever been mounted by a test — issues #97 and #110 were both
 * found by hand, and the #160 token migration was verified by build and
 * contrast math alone. These tests mount the real shell and the real
 * design-system primitives in jsdom.
 *
 * CI still never loads Electron, so these prove the React tree, not the
 * packaged runtime; they are the floor B3 screens build on, not the
 * ceiling.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { api } from '../shared/preload-api.js';
import { App } from '../renderer/src/App.js';
import { Banner, Chip, StatusReadout } from '../renderer/src/components/ui.js';
import type { JobDetail, ProjectSummary } from '../shared/ipc-methods.js';

afterEach(() => {
  // RTL's auto-cleanup registers on a global afterEach, which vitest
  // without `globals: true` does not provide — without this, one test's
  // DOM leaks into the next and role queries find doubles.
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = '';
});

/**
 * The declared surface, with the three calls the Dashboard makes resolved
 * to empty results. Everything else keeps the stub's rejecting body: a
 * namespace a test did not anticipate fails loudly instead of silently
 * returning `undefined`.
 */
function stubFerry(): void {
  vi.stubGlobal('ferry', {
    ...api,
    app: {
      ...api.app,
      getStatus: () =>
        Promise.resolve({ sidecarVersion: '0.3.0', protocolVersion: 1, capabilities: [] }),
    },
    job: { ...api.job, list: () => Promise.resolve({ jobs: [] }) },
    source: { ...api.source, listVolumes: () => Promise.resolve({ volumes: [] }) },
    project: { ...api.project, list: () => Promise.resolve({ projects: [] }) },
  });
}

/** Extend the shell stub with one recent job and named projects. */
function stubFerryWithJobs(
  jobs: readonly JobDetail[],
  projects: readonly ProjectSummary[] = [],
): void {
  vi.stubGlobal('ferry', {
    ...api,
    app: {
      ...api.app,
      getStatus: () =>
        Promise.resolve({ sidecarVersion: '0.3.0', protocolVersion: 1, capabilities: [] }),
    },
    job: { ...api.job, list: () => Promise.resolve({ jobs }) },
    source: { ...api.source, listVolumes: () => Promise.resolve({ volumes: [] }) },
    project: { ...api.project, list: () => Promise.resolve({ projects }) },
  });
}

describe('App shell', () => {
  it('mounts the nav, the header, and the default screen', async () => {
    stubFerry();
    render(<App />);

    // The connection readout resolves, so the sidecar path is live.
    await screen.findByText('Sidecar · protocol v1');

    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(nav.querySelector('.nav__wordmark')?.textContent).toContain('ferry');
    expect(screen.getByRole('link', { name: 'Skip to content' })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeTruthy();
    // The Dashboard's own data arrived as well — the shell is not the only
    // thing under test.
    await screen.findByText('Connected sources');
    expect(screen.getByText('Active jobs')).toBeTruthy();
  });

  it('marks the active view and no other', async () => {
    stubFerry();
    render(<App />);
    await screen.findByText('Sidecar · protocol v1');

    const active = document.querySelectorAll('.nav__item--active');
    expect(active).toHaveLength(1);
    expect(active[0]!.getAttribute('aria-current')).toBe('page');
  });

  it('regroups the rail and renames Transfers/Media (R-5)', async () => {
    stubFerry();
    render(<App />);
    await screen.findByText('Sidecar · protocol v1');

    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(
      [...nav.querySelectorAll('.nav__group')].map((g) => g.getAttribute('aria-label')),
    ).toEqual(['Work', 'Library', 'Setup']);
    // One Transfer entry, and Media is `Assets` after AssetDetail.
    expect([...nav.querySelectorAll('.nav__item')].map((b) => b.textContent)).toEqual([
      'Dashboard',
      'Transfer',
      'Activity',
      'Projects',
      'Assets',
      'Destinations',
      'Presets',
      'Environment',
      'Settings',
    ]);
    // Work is the body; Library and Setup are the two pinned footer runs.
    expect(nav.querySelector('.nav__footer')?.querySelectorAll('.nav__group')).toHaveLength(2);
  });

  it('shows the transfer dock in flight, and cancels through job.cancel (R-4)', async () => {
    const cancel = vi.fn(() => Promise.resolve({}));
    // SAFETY: tsc checks the fixture against the wire type.
    const running: JobDetail = {
      id: 'job-t1',
      projectId: null,
      sessionId: null,
      command: 'transfer',
      argsFingerprint: null,
      state: 'running',
      currentStep: 'transfer',
      totalSteps: 2,
      startedAt: '2026-09-15T00:00:00Z',
      updatedAt: '2026-09-15T00:01:00Z',
      finishedAt: null,
      error: null,
      resumable: false,
    };
    vi.stubGlobal('ferry', {
      ...api,
      app: {
        ...api.app,
        getStatus: () =>
          Promise.resolve({ sidecarVersion: '0.3.0', protocolVersion: 1, capabilities: [] }),
      },
      job: { ...api.job, list: () => Promise.resolve({ jobs: [running] }), cancel },
      source: { ...api.source, listVolumes: () => Promise.resolve({ volumes: [] }) },
      project: { ...api.project, list: () => Promise.resolve({ projects: [] }) },
    });
    render(<App />);
    await screen.findByText('Sidecar · protocol v1');

    const dock = await screen.findByRole('complementary', { name: 'Active transfer' });
    expect(dock.textContent).toContain('Transferring');
    fireEvent.click(within(dock).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith('job-t1'));
  });

  it('has no dock when nothing is in flight (R-4)', async () => {
    stubFerry();
    render(<App />);
    await screen.findByText('Sidecar · protocol v1');
    expect(screen.queryByRole('complementary', { name: 'Active transfer' })).toBeNull();
  });

  it('keeps every nav item named for assistive tech (R-2 relies on it)', async () => {
    // The collapsed rail hides the labels *visually*; if the label were
    // removed instead, the buttons would lose their names at <=999px.
    stubFerry();
    render(<App />);
    await screen.findByText('Sidecar · protocol v1');
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    for (const label of [
      'Dashboard',
      'Transfer',
      'Activity',
      'Projects',
      'Assets',
      'Destinations',
      'Presets',
      'Environment',
      'Settings',
    ]) {
      expect(within(nav).getByRole('button', { name: label })).toBeTruthy();
    }
  });

  it('collapses the header to one line (R-6)', async () => {
    stubFerry();
    render(<App />);
    await screen.findByText('Sidecar · protocol v1');

    const title = screen.getByRole('heading', { level: 1, name: 'Dashboard' });
    // The kicker and the fixed subtitle are gone, and the description is
    // not rendered at all — not as visible text, and not as a mouse-only
    // `title` attribute (which is not an accessible tooltip).
    expect(document.querySelector('.header__kicker')).toBeNull();
    expect(document.querySelector('.header__subtitle')).toBeNull();
    expect(title.hasAttribute('title')).toBe(false);
    expect(screen.queryByText('Jobs and connected sources at a glance')).toBeNull();
  });
});

describe('Dashboard project column', () => {
  // Full literal; SAFETY: tsc checks the fixture against the wire types.
  const PROJECT = {
    id: 'b72d0dbe-610f-48ad-bcc6-5ebd80005027',
    name: 'Moon Landing',
    workingRoot: '/Users/dspury/Moon Landing',
    backupRoot: null,
    status: 'active',
    storagePolicy: {
      requiredReplicas: 2,
      backupOnDifferentVolume: true,
      checksumAlgo: 'xxhash64' as const,
      safetyReserveBytes: 0,
      requireSourceFingerprint: true,
    },
    createdAt: '2026-09-14T00:00:00Z',
    updatedAt: '2026-09-14T00:00:00Z',
    archivedAt: null,
  };
  const JOB = {
    id: 'job-recent',
    projectId: PROJECT.id,
    sessionId: null,
    command: 'organize',
    argsFingerprint: null,
    state: 'succeeded',
    currentStep: null,
    totalSteps: 1,
    startedAt: '2026-09-14T00:00:02Z',
    updatedAt: '2026-09-14T00:00:03Z',
    finishedAt: '2026-09-14T00:00:03Z',
    error: null,
    resumable: false,
  };

  it('names a recent job project instead of printing its UUID', async () => {
    stubFerryWithJobs([JOB], [PROJECT]);
    render(<App />);
    await screen.findByText('Connected sources');
    await screen.findByText('Moon Landing');
    // The full UUID never renders; the elided fallback is for unknown ids.
    const cell = screen.getByText('Moon Landing');
    expect(cell.closest('tr')?.textContent).not.toContain(PROJECT.id);
  });
});
describe('design-system primitives', () => {
  it('Chip carries the tone in shape and text, never colour alone', () => {
    render(<Chip tone="danger">MISSING</Chip>);
    const chip = screen.getByText('MISSING').closest('.chip');
    expect(chip).toBeTruthy();
    expect(chip!.className).toContain('chip--danger');
    // The dot is a non-colour channel: hidden from AT, present in the DOM.
    expect(chip!.querySelector('.chip__dot')).toBeTruthy();
  });

  it('Banner carries a severity word and an alert role for danger', () => {
    render(<Banner tone="danger">3 of 412 files failed verification</Banner>);
    const banner = screen.getByText(/3 of 412 files failed/).closest('.banner');
    expect(banner!.getAttribute('role')).toBe('alert');
    // The stamped prefix is the non-colour signal.
    expect(banner!.querySelector('.banner__label')).toBeTruthy();
  });

  it('StatusReadout is a live region only when it asks to be', () => {
    const { rerender } = render(
      <StatusReadout tone="ok" live>
        Sidecar · protocol v1
      </StatusReadout>,
    );
    expect(screen.getByRole('status')).toBeTruthy();
    rerender(<StatusReadout tone="ok">Idle</StatusReadout>);
    expect(screen.queryByRole('status')).toBeNull();
  });
});

describe('brand tokens (the #160 migration, pinned)', () => {
  const css = readFileSync(
    join(import.meta.dirname, '..', 'renderer', 'src', 'styles.css'),
    'utf8',
  );

  function token(name: string): string {
    const match = new RegExp(`^\\s*${name}: ([^;]+);`, 'm').exec(css);
    const value = match?.[1];
    if (value === undefined) {
      throw new Error(`${name} is not defined in styles.css`);
    }
    return value.trim();
  }

  it('carries the migrated palette values', () => {
    const expected = {
      '--c-rail': '#0A0E16',
      '--c-bg': '#0F1622',
      '--c-surface': '#151E2D',
      '--c-surface-2': '#1C283B',
      '--c-surface-3': '#223046',
      '--c-border': '#243042',
      '--c-border-strong': '#36465D',
      '--c-border-indicator': '#687687',
      '--c-text': '#EDEBE6',
      '--c-text-dim': '#A6A7A7',
      '--c-text-faint': '#919497',
      '--c-accent': '#75A1C6',
      '--c-accent-hover': '#99B9D3',
      '--c-accent-soft': '#1D2939',
      '--c-accent-line': 'rgba(117, 161, 198, 0.65)',
      '--c-accent-interactive': '#54A4E7',
      '--c-on-accent': '#0F1622',
      '--c-ok': '#35a96c',
      '--c-ok-soft': '#14282B',
      '--c-ok-line': 'rgba(53, 169, 108, 0.65)',
      '--c-warn': '#e7b923',
      '--c-warn-soft': '#292A22',
      '--c-warn-line': 'rgba(231, 185, 35, 0.5)',
      '--c-danger': '#f0495a',
      '--c-danger-soft': '#2A1C29',
      '--c-danger-line': 'rgba(240, 73, 90, 0.78)',
      '--c-attention': '#c391e0',
      '--c-attention-soft': '#252539',
      '--c-attention-line': 'rgba(195, 145, 224, 0.6)',
      '--c-cancelled': '#8d94a0',
      '--c-cancelled-soft': '#1E2531',
      '--c-cancelled-line': 'rgba(141, 148, 160, 0.65)',
      '--c-neutral-soft': '#1D2430',
      '--c-scrim': 'rgba(6, 10, 17, 0.66)',
    } satisfies Record<string, string>;
    expect(Object.keys(expected)).toHaveLength(34);
    for (const [name, value] of Object.entries(expected)) {
      expect(token(name)).toBe(value);
    }
  });

  it('has a relative type scale, and no legacy orange anywhere', () => {
    for (const name of [
      '--fs-2xs',
      '--fs-xs',
      '--fs-sm',
      '--fs-md',
      '--fs-lg',
      '--fs-xl',
      '--fs-2xl',
    ]) {
      expect(token(name)).toMatch(/rem$/);
    }
    // The accent glow is the accent at 30% — the last orange in the sheet
    // until the guide corrected it (BRAND-STYLE-GUIDE 6234a08).
    expect(css).not.toContain('255, 106, 44');
    expect(token('--glow-accent')).toBe('0 0 10px rgba(117, 161, 198, 0.3)');
  });
});
