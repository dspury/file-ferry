/**
 * Projects screen.
 *
 * Project list with storage-policy health and asset/replica/derivative
 * aggregates (plan §8.2). The detail view for a single project arrives
 * with the Asset/Clip detail flow; this screen lists and lets you select.
 */
import { useAsync } from '../hooks/useAsync.js';
import { Chip, EmptyState, Panel, ScreenError, ScreenLoading } from '../components/ui.js';
import { projectRow, policyHealthLabel, policyLabel } from '../lib/projects.js';
import { navigateTo } from '../views.js';
import type { JSX } from 'react';

export function Projects(): JSX.Element {
  const projects = useAsync(() => window.ferry.project.list());
  const assets = useAsync(() => window.ferry.asset.list());

  const loading = projects.loading || assets.loading;
  const error = projects.error ?? assets.error;

  if (loading) {
    return (
      <ScreenLoading
        message="Reading projects and their policy…"
        hint="Storage-policy health is computed from what is already recorded; nothing is scanned."
      />
    );
  }
  if (error !== null) {
    return (
      <ScreenError
        message={error}
        onRetry={() => {
          projects.reload();
          assets.reload();
        }}
      />
    );
  }

  const projectList = projects.data?.projects ?? [];
  const assetList = assets.data?.assets ?? [];

  if (projectList.length === 0) {
    return (
      <div className="page">
        <Panel>
          <EmptyState
            message="No projects yet"
            hint="A project is created as part of an offload — it is what destinations, assets, and receipts hang off."
            action={
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => navigateTo('ingest')}
              >
                Go to Offload
              </button>
            }
          />
        </Panel>
      </div>
    );
  }

  return (
    <div className="page">
      <Panel title="Projects" description={`${projectList.length} total`} flush>
        <div className="table-wrap">
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
                      {/*
                        Ghost-styled, not a bordered button: this navigates
                        rather than performing an action, and a box around
                        every name made the list look like a form. It carries
                        the project into Media as a filter, so the link lands
                        on that project's assets instead of all of them.
                      */}
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => navigateTo('asset', { project: p.id })}
                      >
                        {p.name}
                      </button>
                    </td>
                    <td>
                      {/*
                        The label names the finding, not the severity: "no
                        backup root" tells an operator what to fix, where
                        "danger" only told them to worry.
                      */}
                      <Chip tone={row.health}>{policyHealthLabel(row.health)}</Chip>
                    </td>
                    <td className="muted">{policyLabel(p.storagePolicy)}</td>
                    <td className="muted">{p.createdAt.slice(0, 10)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
