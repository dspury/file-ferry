/**
 * Desktop shell. Renders the nav, header, and the active screen based on
 * the URL hash. It does not import filesystem, database, or node APIs; it
 * only consumes the `window.ferry` API exposed by the preload.
 */
import { useEffect, useMemo, useState } from 'react';
import type { FerryAPI } from '../../shared/preload-api.js';
import { activeViewId, flattenViews, navigateTo, type NavGroup, type ViewDef } from './views.js';
import { viewIndex, moveIndex, keyToAction } from './lib/nav.js';
import {
  IconActivity,
  IconDashboard,
  IconEnvironment,
  IconFerry,
  IconMedia,
  IconOffload,
  IconOrganize,
  IconProjects,
  IconSettings,
} from './components/icons.js';
import { Onboarding } from './screens/Onboarding.js';
import { Home } from './screens/Home.js';
import { Projects } from './screens/Projects.js';
import { Ingest } from './screens/Ingest.js';
import { Organize } from './screens/Organize.js';
import { Activity } from './screens/Activity.js';
import { AssetDetail } from './screens/AssetDetail.js';
import { Settings } from './screens/Settings.js';

declare global {
  interface Window {
    readonly ferry: FerryAPI;
  }
}

/*
 * The view ids are the hash route and must not change — `#/ingest` is what
 * a reload or a deep link resolves against. The labels are what an operator
 * reads, so those are named for the task ("Offload") rather than the
 * internal stage name.
 */
const NAV_GROUPS: readonly NavGroup[] = [
  {
    id: 'overview',
    label: 'Overview',
    views: [
      {
        id: 'home',
        label: 'Dashboard',
        description: 'Jobs, connected sources, and library health at a glance',
        icon: IconDashboard,
        component: Home,
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
    id: 'transfer',
    label: 'Transfer',
    views: [
      {
        id: 'ingest',
        label: 'Offload',
        description: 'Copy a camera card, verify every byte, and keep the receipt',
        icon: IconOffload,
        component: Ingest,
      },
      {
        id: 'organize',
        label: 'Organize',
        description: 'Preview a folder structure over existing media, then apply it',
        icon: IconOrganize,
        component: Organize,
      },
    ],
  },
  {
    id: 'library',
    label: 'Library',
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
        label: 'Media',
        description: 'Metadata, replicas, proxy state, and clip grouping',
        icon: IconMedia,
        component: AssetDetail,
      },
    ],
  },
  {
    id: 'system',
    label: 'System',
    footer: true,
    views: [
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
  const [viewId, setViewId] = useState<string>(() => activeViewId('home'));
  const [status, setStatus] = useState<ShellStatus>(CONNECTING);

  useEffect(() => {
    const onHashChange = () => setViewId(activeViewId('home'));
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

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
      navigateTo(VIEWS[moveIndex(activeIndex, 1, VIEWS.length)]!.id);
      e.preventDefault();
    } else if (action === 'prev') {
      navigateTo(VIEWS[moveIndex(activeIndex, -1, VIEWS.length)]!.id);
      e.preventDefault();
    }
  };

  const body = NAV_GROUPS.filter((g) => g.footer !== true);
  const footer = NAV_GROUPS.filter((g) => g.footer === true);

  return (
    <div className="app">
      <a href="#content" className="skip-link">
        Skip to content
      </a>
      <nav className="nav" aria-label="Primary" onKeyDown={onNavKeyDown}>
        <div className="nav__brand">
          <span className="nav__mark" aria-hidden="true">
            <IconFerry size={17} />
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
        <h1 className="header__title">{active.label}</h1>
        <p className="header__subtitle">{active.description}</p>
        <div className="header__actions">
          {/*
            A live region: the sidecar going away mid-session is something
            the operator has to know about, and the rail is the one place
            on screen that never scrolls out of view.
          */}
          <span className={`status status--${status.tone}`} role="status">
            <span className="status__dot" aria-hidden="true" />
            {status.text}
          </span>
        </div>
      </header>

      <main id="content" className="content" tabIndex={-1}>
        <div className="content__inner">
          <ActiveScreen />
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
