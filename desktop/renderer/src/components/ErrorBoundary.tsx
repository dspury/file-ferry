/**
 * Last-resort render-crash boundary around the routed screen (#97).
 *
 * Before this existed, any exception thrown during a screen's render — a
 * payload field the code assumed was there, a stale deep link, any future
 * bug — unwound React's commit and unmounted the entire tree. The window
 * went blank: not the panel, the whole app, nav included, with no path
 * back short of a restart. There was no boundary anywhere above the
 * screens.
 *
 * It sits around `<ActiveScreen />` and only there, deliberately inside
 * the shell rather than above it: a screen that crashes must not take the
 * rail, the header, or the sidecar-status readout with it, because those
 * are exactly what the operator needs to navigate away from the wreck.
 * The boundary is remounted per view (`key`), so a crash on Media never
 * paints Dashboard's fallback, and returning to a crashed view re-attempts
 * it with fresh state rather than replaying the cached error.
 *
 * The fallback offers the two recoveries that exist for a render error:
 * retry the screen (the error may have been a transient payload), or use
 * the still-alive nav to go elsewhere. It does not offer "reload the
 * window", because the hash router restores the same route on reload —
 * which would reproduce the same crash, not clear it.
 *
 * A class component because React 18 error boundaries are class-only:
 * `getDerivedStateFromError` / `componentDidCatch` have no hook
 * equivalent. Every other component in the renderer is a function; this
 * is the one place the framework requires otherwise.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Banner } from './ui.js';

interface ErrorBoundaryProps {
  readonly children: ReactNode;
}

interface ErrorBoundaryState {
  readonly error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // The renderer has no logging transport of its own; the console is
    // captured by the diagnostic flow if the operator ever exports one.
    // The component stack is the part worth keeping — it names the screen
    // component that threw, which the Error message alone never does.
    console.error('screen render failed:', error, info.componentStack);
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (error === null) return this.props.children;

    return (
      <div className="page">
        <Banner tone="danger" label="This screen failed to draw">
          The rest of the app is still running — the nav and every other screen are unaffected.
          Nothing was written or deleted; this is a display failure, not an operation failure.
        </Banner>
        <div className="row">
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => {
              // Clears the held error; the children remount on the next
              // render, so the retry is a fresh mount rather than a resume
              // of whatever half-rendered state threw.
              this.setState({ error: null });
            }}
          >
            Try again
          </button>
        </div>
        <div className="card__body">
          <code>{error.message}</code>
        </div>
      </div>
    );
  }
}
