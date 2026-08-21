/**
 * Projects screen.
 *
 * Project list with storage-policy health and asset/replica/derivative
 * aggregates (plan §8.2). The detail view for a single project arrives
 * with the Asset/Clip detail flow; this screen lists and lets you select.
 */
import { useAsync } from '../hooks/useAsync.js';
import { Chip, Panel, LoadingState, ErrorState } from '../components/ui.js';
import { projectRow, policyLabel } from '../lib/projects.js';
import { navigateTo } from '../views.js';

export function Projects(): JSX.Element {
  const projects = useAsync(() => window.ferry.project.list());
  const assets = useAsync(() => window.ferry.asset.list());

  const loading = projects.loading || assets.loading;
  const error = projects.error ?? assets.error;

  if (loading) {
    return <LoadingState message="Loading projects…" />;
  }
  if (error !== null) {
    return <ErrorState message={error} />;
  }

  const projectList = projects.data?.projects ?? [];
  const assetList = assets.data?.assets ?? [];

  if (projectList.length === 0) {
    return (
      <div className="stack">
        <h2>Projects</h2>
        <Panel>
          <p className="muted">No projects yet. Create one from the Ingest flow.</p>
        </Panel>
      </div>
    );
  }

  return (
    <div className="stack">
      <h2>Projects</h2>
      <Panel>
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Policy health</th>
              <th>Policy</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {projectList.map((p) => {
              const row = projectRow(p, assetList, [], []);
              return (
                <tr key={p.id}>
                  <td>
                    <button className="btn" onClick={() => navigateTo('asset')}>
                      {p.name}
                    </button>
                  </td>
                  <td>
                    <Chip tone={row.health}>{row.health}</Chip>
                  </td>
                  <td className="muted">{policyLabel(p.storagePolicy)}</td>
                  <td className="muted">{p.createdAt.slice(0, 10)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
