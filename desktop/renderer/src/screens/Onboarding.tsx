/**
 * Onboarding / Doctor screen.
 *
 * Shows dependency health (ffmpeg/ffprobe/resolve), storage roots, the
 * app data location, and a summary of the safety posture. The screen is
 * the first thing a real install should surface so missing tools and
 * data locations are explained (plan §10 Pkg7 step 1, §8.2).
 */
import { useAsync } from '../hooks/useAsync.js';
import { Chip, Panel, LoadingState, ErrorState } from '../components/ui.js';
import { toolTone, formatBytes } from '../lib/doctor.js';

export function Onboarding(): JSX.Element {
  const doctor = useAsync(() => window.ferry.app.doctor());
  const volumes = useAsync(() => window.ferry.source.listVolumes());

  if (doctor.loading) {
    return <LoadingState message="Running environment check…" />;
  }
  if (doctor.error !== null) {
    return <ErrorState message={doctor.error} />;
  }
  const d = doctor.data;
  if (d === null) {
    return <ErrorState message="No doctor data." />;
  }

  return (
    <div className="stack">
      <h2>Environment check</h2>

      <Panel title="Dependencies">
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
                <td className="muted">{tool.path ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Storage roots">
        {volumes.loading ? (
          <p className="muted">Scanning volumes…</p>
        ) : volumes.error !== null ? (
          <p className="muted">Unable to read volumes: {volumes.error}</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Mount</th>
                <th>Filesystem</th>
                <th>Free / Total</th>
              </tr>
            </thead>
            <tbody>
              {(volumes.data?.volumes ?? []).map((v) => (
                <tr key={v.path}>
                  <td>{v.path}</td>
                  <td>{v.filesystem}</td>
                  <td className="muted">
                    {formatBytes(v.freeBytes)} / {formatBytes(v.totalBytes)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Data location">
        <p>
          <span className="muted">App data:</span> <code>{d.appDataDir}</code>
        </p>
        <p>
          <span className="muted">Database:</span> <code>{d.dbPath}</code>
        </p>
        <p className="muted">
          Sidecar v{d.version} · protocol v{d.protocolVersion}
        </p>
      </Panel>
    </div>
  );
}
