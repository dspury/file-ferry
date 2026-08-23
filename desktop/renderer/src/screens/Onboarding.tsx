/**
 * Environment / Doctor screen.
 *
 * Shows dependency health (ffmpeg/ffprobe/resolve), storage roots, the
 * app data location, and a summary of the safety posture. The screen is
 * the first thing a real install should surface so missing tools and
 * data locations are explained (plan §10 Pkg7 step 1, §8.2).
 */
import { useAsync } from '../hooks/useAsync.js';
import {
  Banner,
  Chip,
  EmptyState,
  KeyValue,
  LoadingState,
  Panel,
  PathCell,
  ScreenError,
  ScreenLoading,
} from '../components/ui.js';
import { toolTone, formatBytes } from '../lib/doctor.js';

export function Onboarding(): JSX.Element {
  const doctor = useAsync(() => window.ferry.app.doctor());
  const volumes = useAsync(() => window.ferry.source.listVolumes());

  if (doctor.loading) {
    return (
      <ScreenLoading
        message="Checking the environment…"
        hint="Looking for ffmpeg, ffprobe, and Resolve, and reading volume headroom. Read-only."
      />
    );
  }
  if (doctor.error !== null) {
    return <ScreenError message={doctor.error} onRetry={doctor.reload} />;
  }
  const d = doctor.data;
  if (d === null) {
    return (
      <ScreenError
        message="The sidecar answered the environment check with no data."
        onRetry={doctor.reload}
      />
    );
  }

  const missing = d.tools.filter((t) => !t.present);

  return (
    <div className="page">
      {/*
        Lead with the verdict. The tables below are the evidence, but the
        one thing an operator needs on arriving here is whether anything is
        wrong, and `toolTone` already knows which absences actually matter.
      */}
      {missing.length === 0 ? (
        <Banner tone="ok" label="Ready">
          Every required tool was found.
        </Banner>
      ) : (
        <Banner tone="warn" label="Incomplete">
          {missing.length} tool{missing.length === 1 ? '' : 's'} not found:{' '}
          {missing.map((t) => t.name).join(', ')}. Set an explicit path under Settings → Tool paths,
          or install it on your PATH.
        </Banner>
      )}

      <Panel title="Dependencies" description="External tools ferry shells out to" flush>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Tool</th>
                <th>Status</th>
                <th>Location</th>
              </tr>
            </thead>
            <tbody>
              {d.tools.map((tool) => (
                <tr key={tool.name}>
                  <td>{tool.name}</td>
                  <td>
                    <Chip tone={toolTone(tool.name, tool.present)}>
                      {tool.present ? 'present' : 'missing'}
                    </Chip>
                  </td>
                  <td>
                    <ToolPath path={tool.path ?? null} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        title="Storage roots"
        description="Mounted volumes and their headroom"
        flush={(volumes.data?.volumes ?? []).length > 0}
      >
        {volumes.loading ? (
          <LoadingState message="Scanning volumes…" />
        ) : volumes.error !== null ? (
          <Banner tone="warn">Unable to read volumes: {volumes.error}</Banner>
        ) : (volumes.data?.volumes ?? []).length === 0 ? (
          /* A table head with no rows under it reads as a component that
             failed, not as an answer. This is the answer. */
          <EmptyState
            message="No volumes visible"
            hint="ferry sees no mounted volumes at all — not even a system disk. On macOS that usually means the app has not been granted access to removable volumes yet."
          />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Mount</th>
                  <th>Filesystem</th>
                  <th className="cell-num">Free</th>
                  <th className="cell-num">Total</th>
                </tr>
              </thead>
              <tbody>
                {(volumes.data?.volumes ?? []).map((v) => (
                  <tr key={v.path}>
                    <td>
                      <PathCell path={v.path} />
                    </td>
                    <td className="muted">{v.filesystem}</td>
                    <td className="cell-num">{formatBytes(v.freeBytes)}</td>
                    <td className="cell-num muted">{formatBytes(v.totalBytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Data location" description="Where ferry keeps its own state">
        <KeyValue
          rows={[
            { label: 'App data', value: <code>{d.appDataDir}</code> },
            { label: 'Database', value: <code>{d.dbPath}</code> },
            { label: 'Sidecar', value: `v${d.version}` },
            { label: 'Protocol', value: `v${d.protocolVersion}` },
          ]}
        />
      </Panel>
    </div>
  );
}

function ToolPath({ path }: { path: string | null }): JSX.Element {
  if (path === null) return <span className="faint">—</span>;
  return <PathCell path={path} />;
}
