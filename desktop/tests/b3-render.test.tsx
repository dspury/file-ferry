// @vitest-environment jsdom
/**
 * Render tests for the P6/B3 screens (issue #122).
 *
 * These mount the real screens in jsdom with the declared bridge stub, so
 * a screen that cannot render fails here rather than on a live sidecar.
 * The two views that fetch (Destinations, Presets) get resolved stubs;
 * Transfers' empty route renders its scan stage, which makes no calls.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../shared/preload-api.js';
import type { JsonObject } from '../shared/ipc-schema.js';
import { Destinations } from '../renderer/src/screens/Destinations.js';
import { Presets } from '../renderer/src/screens/Presets.js';
import { Transfers } from '../renderer/src/screens/Transfers.js';

afterEach(() => {
  // See render.test.tsx: auto-cleanup needs a global afterEach this suite
  // does not provide.
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = '';
});

function stub(overrides: Partial<typeof api>): void {
  vi.stubGlobal('ferry', { ...api, ...overrides });
}

// Literal `as const` so the fixture carries the exact literal unions the
// wire type demands instead of widening them to string. SAFETY: the
// fixture's shape is checked against ListDestinationsResult by tsc.
const SAVED_DESTINATION = {
  id: 1,
  name: 'Editing NAS',
  locationKind: 'volume_folder' as const,
  lastRootPath: '/Volumes/NAS/projects',
  subfolderPath: null,
  identity: null,
  defaultPresetId: null,
  pinnedRevision: null,
  conflictPolicy: 'keep_both' as const,
  checksumAlgo: 'xxhash64' as const,
  freeSpaceReserve: 0,
  lastBindingPath: null,
  lastSeenAt: null,
  createdAt: '2026-09-14T00:00:00Z',
  updatedAt: '2026-09-14T00:00:00Z',
  archivedAt: null,
};

const PROFILE = {
  id: 7,
  name: 'Portable',
  version: 1,
  // SAFETY: the fixture's shape is checked against OrganizationProfile by tsc.
  template: {} as JsonObject,
  conflictPolicy: 'keep_both',
  mutationPolicy: 'copy',
  createdAt: '2026-09-14T00:00:00Z',
  updatedAt: '2026-09-14T00:00:00Z',
};

describe('Destinations', () => {
  it('renders the availability of each saved destination, in words', async () => {
    stub({
      destination: {
        ...api.destination,
        list: () => Promise.resolve({ destinations: [SAVED_DESTINATION] }),
        resolve: () =>
          Promise.resolve({
            resolutions: [
              {
                destinationId: 1,
                name: 'Editing NAS',
                status: 'available',
                reason: 'mounted with matching identity',
                candidatePaths: [],
                bindingPath: '/Volumes/NAS/projects',
              },
            ],
          }),
        discovery: () =>
          Promise.resolve({
            volumes: [],
            observedAt: '2026-09-14T00:00:00Z',
            ageSeconds: 0,
            stale: false,
            warnings: [],
          }),
      },
      profile: { ...api.profile, list: () => Promise.resolve({ profiles: [] }) },
    });
    render(<Destinations />);

    await screen.findByText('Editing NAS');
    expect(screen.getByText('available')).toBeTruthy();
    expect(screen.getByText('mounted with matching identity')).toBeTruthy();
    // The saved record and the live answer are visibly separate columns.
    expect(screen.getByText('/Volumes/NAS/projects')).toBeTruthy();
  });

  it('offers the save form on an empty library', async () => {
    stub({
      destination: {
        ...api.destination,
        list: () => Promise.resolve({ destinations: [] }),
        resolve: () => Promise.resolve({ resolutions: [] }),
        discovery: () =>
          Promise.resolve({
            volumes: [],
            observedAt: null,
            ageSeconds: null,
            stale: false,
            warnings: [],
          }),
      },
      profile: { ...api.profile, list: () => Promise.resolve({ profiles: [] }) },
    });
    render(<Destinations />);

    await screen.findByText('No saved destinations');
    // The empty state is not a dead end: it carries the action, and the
    // panel header offers the same one.
    const saveButtons = screen.getAllByRole('button', { name: 'Save destination' });
    expect(saveButtons.length).toBeGreaterThanOrEqual(1);
  });
});

describe('Presets', () => {
  it('lists presets and shows the selected revision content', async () => {
    stub({
      profile: {
        ...api.profile,
        list: () => Promise.resolve({ profiles: [PROFILE] }),
        listRevisions: () =>
          Promise.resolve({
            revisions: [
              {
                presetId: 7,
                revision: 1,
                contentHash: 'abc123def456',
                createdAt: '2026-09-14T00:00:00Z',
                id: 1,
              },
            ],
            total: 1,
          }),
        getRevision: () =>
          Promise.resolve({
            presetId: 7,
            revision: 1,
            createdAt: '2026-09-14T00:00:00Z',
            contentHash: 'abc123def456',
            legacySnapshot: false,
            content: {
              name: 'Portable',
              description: null,
              rules: [],
              groups: [],
              fallbackTemplate: 'Sources/{source_label}/{relative_dir}/{filename}',
              conflictPolicy: 'keep_both',
              exclusions: [],
              reviewRequired: [],
            },
          }),
      },
    });
    render(<Presets />);

    await screen.findByText('Portable');
    // Selecting the preset loads its revisions and the shown content.
    const select = screen.getByRole('button', { name: 'Portable' });
    fireEvent.click(select);
    await screen.findByText('Revisions of Portable');
    expect(await screen.findByText(/Sources\/\{source_label\}/)).toBeTruthy();
  });

  it('says when no presets exist yet', async () => {
    stub({ profile: { ...api.profile, list: () => Promise.resolve({ profiles: [] }) } });
    render(<Presets />);
    await screen.findByText('No presets yet');
  });
});

describe('Transfers (pipeline shell)', () => {
  it('renders the staged pipeline and the scan affordance with no ids in the route', () => {
    stub({});
    render(<Transfers />);
    // The steps rail names the whole flow, and the writing stage is marked.
    const rail = screen.getByRole('list', { name: 'Transfer pipeline' });
    expect(rail.textContent).toContain('Scan');
    expect(rail.textContent).toContain('Approve');
    expect(screen.getByText('Sources')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Scan source' })).toBeTruthy();
  });

  it('disables Scan until a folder is chosen', () => {
    stub({});
    render(<Transfers />);
    const scanButton = screen.getByRole('button', { name: 'Scan source' });
    expect(scanButton.hasAttribute('disabled')).toBe(true);
  });
});
