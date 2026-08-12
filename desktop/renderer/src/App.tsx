/**
 * Foundation renderer. The full Ingest / Organize / Projects / Activity
 * screens land in Package 7 of the implementation plan. This App is the
 * minimum viable surface that proves the security boundary, the IPC
 * bridge, and the sidecar lifecycle are wired correctly.
 *
 * It does not import any filesystem, database, or node APIs. It only
 * consumes the `window.mediaMate` API exposed by the preload script.
 */
import { useEffect, useState } from 'react';
import type { MediaMateAPI } from '../../shared/preload-api.js';

declare global {
  interface Window {
    readonly mediaMate: MediaMateAPI;
  }
}

interface StatusView {
  readonly sidecarVersion: string;
  readonly protocolVersion: number;
  readonly capabilities: readonly string[];
}

export function App(): JSX.Element {
  const [status, setStatus] = useState<StatusView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    window.mediaMate.app
      .getStatus()
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error !== null) {
    return (
      <main className="app app--error">
        <h1>media-mate</h1>
        <p className="error">sidecar unreachable: {error}</p>
      </main>
    );
  }

  if (status === null) {
    return (
      <main className="app">
        <h1>media-mate</h1>
        <p>connecting to sidecar…</p>
      </main>
    );
  }

  return (
    <main className="app">
      <h1>media-mate</h1>
      <p className="tag">vNext foundation · protocol v{status.protocolVersion}</p>
      <p>sidecar {status.sidecarVersion}</p>
      <ul>
        {status.capabilities.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </main>
  );
}
