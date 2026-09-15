/**
 * Desktop shell. Renders the nav, header, and the active screen based on
 * the URL hash. It does not import filesystem, database, or node APIs; it
 * only consumes the `window.ferry` API exposed by the preload.
 */
import { useEffect, useMemo, useRef, useState, type JSX } from 'react';
import { useRoute } from './hooks/useRoute.js';
import type { FerryAPI } from '../../shared/preload-api.js';
import { flattenViews, navigateTo, type NavGroup, type ViewDef } from './views.js';
import { viewIndex, moveIndex, keyToAction } from './lib/nav.js';
import { FerryMark } from './components/FerryMark.js';
import {
  IconActivity,
  IconDashboard,
  IconDestination,
  IconEnvironment,
  IconMedia,
  IconPreset,
  IconProjects,
  IconSettings,
  IconTransfer,
} from './components/icons.js';
import { StatusReadout } from './components/ui.js';
import { ErrorBoundary } from './components/ErrorBoundary.js';
import { Onboarding } from './screens/Onboarding.js';
import { Home } from './screens/Home.js';
import { Projects } from './screens/Projects.js';
import { Activity } from './screens/Activity.js';
import { AssetDetail } from './screens/AssetDetail.js';
import { Settings } from './screens/Settings.js';
import { Destinations } from './screens/Destinations.js';
import { Presets } from './screens/Presets.js';
import { Transfers } from './screens/Transfers.js';

declare global {
  interface Window {
    readonly ferry: FerryAPI;
  }
}

/*
 * The view ids are the hash route. The labels are what an operator reads.
 *
 * R-3 left one Transfer entry (Offload and Organize withdrawn or absorbed).
 * R-5 regrouped the rail: Work holds the daily verbs, and the Library and
 * Setup runs are pinned to the bottom. `Transfers` became `Transfer`, and
 * `Media` became `Assets` after what `AssetDetail.tsx` actually does.
 */
const NAV_GROUPS: readonly NavGroup[] = [
  {
    id: 'work',
    label: 'Work',
    views: [
      {
        id: 'home',
        label: 'Dashboard',
        description: 'Jobs and connected sources at a glance',
        icon: IconDashboard,
        component: Home,
      },
      {
        id: 'transfers',
        label: 'Transfer',
        description: 'Scan a source, review a plan, approve it, and watch the verified copy',
        icon: IconTransfer,
        component: Transfers,
      },
      {
        id: 'activity',
        label: 'Activity',
        description: 'Running, finished, and stalled jobs, with receipts',
        icon: IconActivity,
        component: Activity,
      },
    ],
  },
  {
    id: 'library',
    label: 'Library',
    footer: true,
    views: [
      {
        id: 'projects',
        label: 'Projects',
        description: 'Storage-policy health across every project',
        icon: IconProjects,
        component: Projects,
      },
      {
        id: 'asset',
        // Was "Media", after `AssetDetail.tsx`: the screen browses assets and
        // inspects their replicas, proxies, and clips, which "Media" named
        // only by file type.
        label: 'Assets',
        description: 'Browse the library, then inspect replicas, proxies, and clips',
        icon: IconMedia,
        component: AssetDetail,
      },
    ],
  },
  {
    id: 'setup',
    label: 'Setup',
    footer: true,
    views: [
      {
        id: 'destinations',
        label: 'Destinations',
        description: 'Saved locations, their live availability, and the presets pinned to them',
        icon: IconDestination,
        component: Destinations,
      },
      {
        id: 'presets',
        label: 'Presets',
        description: 'Immutable routing rules, as revisions you can audit',
        icon: IconPreset,
        component: Presets,
      },
      {
        id: 'onboarding',
        label: 'Environment',
        description: 'Dependencies, storage roots, and where your data lives',
        icon: IconEnvironment,
        component: Onboarding,
      },
      {
        id: 'settings',
        label: 'Settings',
        description: 'Proxy, checksum, tool path, and organization defaults',
        icon: IconSettings,
        component: Settings,
      },
    ],
  },
];

const VIEWS = flattenViews(NAV_GROUPS);

interface ShellStatus {
  readonly tone: 'ok' | 'danger' | 'neutral';
  readonly text: string;
}

const CONNECTING: ShellStatus = { tone: 'neutral', text: 'Connecting…' };

export function App(): JSX.Element {
  const viewId = useRoute('home').viewId;
  const [status, setStatus] = useState<ShellStatus>(CONNECTING);

  useEffect(() => {
    let cancelled = false;
    window.ferry.app
      .getStatus()
      .then((s) => {
        if (!cancelled) setStatus({ tone: 'ok', text: `Sidecar · protocol v${s.protocolVersion}` });
      })
      .catch(() => {
        if (!cancelled) setStatus({ tone: 'danger', text: 'Sidecar unreachable' });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const navRef = useRef<HTMLElement>(null);
  const followFocus = useRef(false);

  const active = useMemo(() => VIEWS.find((v) => v.id === viewId) ?? VIEWS[0]!, [viewId]);
  const ActiveScreen = active.component;
  const viewIds = VIEWS.map((v) => v.id);
  const activeIndex = viewIndex(viewId, viewIds);

  // Keyboard navigation: ArrowDown/Up move between views (plan §10 Pkg7
  // step 4). The handler is bound to the nav, not the app root — at the
  // root it also swallowed arrow keys aimed at the screens, so ArrowUp in
  // a <select> or a number input silently navigated away from the form.
  // It traverses the flattened list, so it crosses group boundaries in the
  // same order the groups are drawn.
  const onNavKeyDown = (e: React.KeyboardEvent) => {
    const action = keyToAction(e.key, e.ctrlKey, e.altKey);
    if (action === 'next') {
      followFocus.current = true;
      navigateTo(VIEWS[moveIndex(activeIndex, 1, VIEWS.length)]!.id);
      e.preventDefault();
    } else if (action === 'prev') {
      followFocus.current = true;
      navigateTo(VIEWS[moveIndex(activeIndex, -1, VIEWS.length)]!.id);
      e.preventDefault();
    }
    // `activate` is deliberately unhandled: Enter and Space already press a
    // <button>, and claiming them here would only re-implement that.
  };

  /*
   * Focus has to follow an arrow key, or the ring stays on the item the
   * operator left. ArrowDown from Dashboard moved the route to Activity and
   * left the visible focus on Dashboard: the one indicator saying "you are
   * here" pointed at the wrong row, and a screen reader was told nothing at
   * all, because nothing it was watching had changed.
   *
   * Gated on the flag rather than run on every route change: a click already
   * focuses the button it pressed, and a link inside a screen ("View all in
   * Activity") must be allowed to leave focus in the content it came from.
   */
  useEffect(() => {
    if (!followFocus.current) return;
    followFocus.current = false;
    navRef.current?.querySelector<HTMLButtonElement>('.nav__item--active')?.focus();
  }, [viewId]);

  const body = NAV_GROUPS.filter((g) => g.footer !== true);
  const footer = NAV_GROUPS.filter((g) => g.footer === true);

  return (
    <div className="app">
      <a href="#content" className="skip-link">
        Skip to content
      </a>
      <nav className="nav" aria-label="Primary" ref={navRef} onKeyDown={onNavKeyDown}>
        <div className="nav__brand">
          <span className="nav__mark" aria-hidden="true">
            <FerryMark />
          </span>
          <span className="nav__wordmark">
            ferry
            <span className="nav__tagline">Media manager</span>
          </span>
        </div>

        {body.map((group) => (
          <NavGroupList key={group.id} group={group} activeId={active.id} />
        ))}

        <div className="nav__spacer" />

        <div className="nav__footer">
          {footer.map((group) => (
            <NavGroupList key={group.id} group={group} activeId={active.id} />
          ))}
        </div>
      </nav>

      <header className="header">
        {/*
          R-6: one line — title left, sidecar status right. The kicker and
          the fixed per-view subtitle were three lines of chrome that never
          changed and never reacted to state, so both are gone; the nav
          already names the view.

          The description is dropped from the header rather than moved to a
          `title` attribute: `title` is not an accessible tooltip — it does
          not appear on keyboard focus, is absent on touch, and is announced
          inconsistently — so a string that used to be visible text for
          everyone would become mouse-only. `ViewDef.description` stays on
          the type for screens that may want it later. Removing the subtitle
          is also what removes the 760px title/subtitle collision R-2
          measured.
        */}
        <h1 className="header__title">{active.label}</h1>
        <div className="header__actions">
          {/*
            A live region: the sidecar going away mid-session is something
            the operator has to know about, and the rail is the one place
            on screen that never scrolls out of view.
          */}
          <StatusReadout tone={status.tone} live>
            {status.text}
          </StatusReadout>
        </div>
      </header>

      <main id="content" className="content" tabIndex={-1}>
        <div className="content__inner">
          {/*
            The boundary is keyed by view id so each route gets a fresh one:
            a crash held on one screen must not paint another screen's
            fallback, and revisiting a crashed screen re-attempts the render
            instead of replaying the cached error (#97).
          */}
          <ErrorBoundary key={active.id}>
            <ActiveScreen />
          </ErrorBoundary>
        </div>
      </main>
    </div>
  );
}

/**
 * One labelled run of nav buttons. The visible heading is `aria-hidden`
 * because the group is already named by `aria-label` — announcing both
 * would read the heading twice.
 */
function NavGroupList({ group, activeId }: { group: NavGroup; activeId: string }): JSX.Element {
  return (
    <div className="nav__group" role="group" aria-label={group.label}>
      <div className="nav__group-label" aria-hidden="true">
        {group.label}
      </div>
      {group.views.map((view) => (
        <NavItem key={view.id} view={view} active={view.id === activeId} />
      ))}
    </div>
  );
}

/*
 * A plain group of buttons, not role="menu". `menu`/`menuitem` model an
 * application menu (File, Edit) and make assistive tech announce and
 * key-handle this as one; it is page navigation, which `aria-current="page"`
 * already conveys. `aria-keyshortcuts` is gone for the same reason — it
 * declares keys that *activate* an element, while ArrowUp/Down here move
 * between them.
 */
function NavItem({ view, active }: { view: ViewDef; active: boolean }): JSX.Element {
  const Glyph = view.icon;
  return (
    <button
      type="button"
      className={`nav__item${active ? ' nav__item--active' : ''}`}
      onClick={() => navigateTo(view.id)}
      aria-current={active ? 'page' : undefined}
    >
      <Glyph size={16} />
      {view.label}
    </button>
  );
}
