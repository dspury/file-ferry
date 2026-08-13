/**
 * Desktop shell. Renders the nav, header, and the active screen based on
 * the URL hash. It does not import filesystem, database, or node APIs; it
 * only consumes the `window.mediaMate` API exposed by the preload.
 *
 * Package 7a: the shell, nav, and design system are wired here; the
 * screens are placeholders until 7b/7c/7d.
 */
import { useEffect, useMemo, useState } from 'react';
import type { MediaMateAPI } from '../../shared/preload-api.js';
import { activeViewId, navigateTo, type ViewDef } from './views.js';
import { viewIndex, moveIndex, keyToAction } from './lib/nav.js';
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
    readonly mediaMate: MediaMateAPI;
  }
}

const VIEWS: readonly ViewDef[] = [
  { id: 'onboarding', label: 'Onboarding', component: Onboarding },
  { id: 'home', label: 'Home', component: Home },
  { id: 'projects', label: 'Projects', component: Projects },
  { id: 'ingest', label: 'Ingest', component: Ingest },
  { id: 'organize', label: 'Organize', component: Organize },
  { id: 'activity', label: 'Activity', component: Activity },
  { id: 'asset', label: 'Asset / Clip', component: AssetDetail },
  { id: 'settings', label: 'Settings', component: Settings },
];

export function App(): JSX.Element {
  const [viewId, setViewId] = useState<string>(() => activeViewId('home'));
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    const onHashChange = () => setViewId(activeViewId('home'));
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    let cancelled = false;
    window.mediaMate.app
      .getStatus()
      .then((s) => {
        if (!cancelled) setStatus(`protocol v${s.protocolVersion}`);
      })
      .catch(() => {
        if (!cancelled) setStatus('sidecar unreachable');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const active = useMemo(() => VIEWS.find((v) => v.id === viewId) ?? VIEWS[0]!, [viewId]);
  const ActiveScreen = active.component;
  const viewIds = VIEWS.map((v) => v.id);
  const activeIndex = viewIndex(viewId, viewIds);

  // Keyboard navigation: ArrowDown/Up move between views, Enter/Space
  // activates the focused one (plan §10 Pkg7 step 4).
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

  return (
    <div className="app" onKeyDown={onNavKeyDown}>
      <a href="#content" className="skip-link">
        Skip to content
      </a>
      <nav className="nav" aria-label="Primary">
        <div className="nav__brand">
          media-mate
          <small>vNext desktop</small>
        </div>
        <div role="menu" aria-label="Views">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              role="menuitem"
              className={`nav__item${v.id === active.id ? ' nav__item--active' : ''}`}
              onClick={() => navigateTo(v.id)}
              aria-current={v.id === active.id ? 'page' : undefined}
              aria-keyshortcuts="ArrowDown ArrowUp"
            >
              {v.label}
            </button>
          ))}
        </div>
      </nav>
      <header className="header">
        <span className="header__title">{active.label}</span>
        <span className="header__status">{status ?? 'connecting…'}</span>
      </header>
      <main id="content" className="content" tabIndex={-1}>
        <ActiveScreen />
      </main>
    </div>
  );
}
