/**
 * Ingest screen.
 *
 * Camera-card offload following plan -> review -> execute -> verify ->
 * receipt (plan §4.2). This screen drives source pick/inspect, project
 * + destination selection, plan build, and reviewable plan. Execution is
 * deliberately a separate, explicit action (create job) — never an
 * optimistic success; the stage gates on real plan data.
 */
import { useState } from 'react';
import { useAsync } from '../hooks/useAsync.js';
import { Chip, Panel, Field } from '../components/ui.js';
import {
  ingestStage,
  planReviewable,
  planBlocked,
  sourceReady,
  capacityLabel,
  formatBytes,
} from '../lib/ingest.js';
import type { IntakePlan, SourceInspectResult } from '../../../shared/ipc-methods.js';

export function Ingest(): JSX.Element {
  const projects = useAsync(() => window.mediaMate.project.list());

  const [sourcePath, setSourcePath] = useState<string | null>(null);
  const [source, setSource] = useState<SourceInspectResult | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [inspectError, setInspectError] = useState<string | null>(null);

  const [projectId, setProjectId] = useState<string>('');
  const [workingRoot, setWorkingRoot] = useState<string | null>(null);
  const [backupRoot, setBackupRoot] = useState<string | null>(null);

  const [plan, setPlan] = useState<IntakePlan | null>(null);
  const [building, setBuilding] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

  const [executing, setExecuting] = useState(false);
  const [executed, setExecuted] = useState(false);
  const [executeError, setExecuteError] = useState<string | null>(null);

  const pickSource = async () => {
    const result = await window.mediaMate.dialog.pick({ kind: 'directory' });
    if (!result.cancelled && result.path) setSourcePath(result.path);
  };

  const inspect = async () => {
    if (!sourcePath) return;
    setInspecting(true);
    setInspectError(null);
    setSource(null);
    try {
      const s = await window.mediaMate.source.inspect({ path: sourcePath, kind: 'card' });
      setSource(s);
    } catch (err) {
      setInspectError(err instanceof Error ? err.message : String(err));
    } finally {
      setInspecting(false);
    }
  };

  const pickWorking = async () => {
    const r = await window.mediaMate.dialog.pick({ kind: 'directory' });
    if (!r.cancelled && r.path) setWorkingRoot(r.path);
  };

  const pickBackup = async () => {
    const r = await window.mediaMate.dialog.pick({ kind: 'directory' });
    if (!r.cancelled && r.path) setBackupRoot(r.path);
  };

  const buildPlan = async () => {
    if (!source || !projectId) return;
    const destinations = [
      ...(workingRoot ? [{ kind: 'working' as const, rootPath: workingRoot }] : []),
      ...(backupRoot ? [{ kind: 'backup' as const, rootPath: backupRoot }] : []),
    ];
    setBuilding(true);
    setPlanError(null);
    setPlan(null);
    try {
      const p = await window.mediaMate.plan.build({
        projectId,
        sourceId: source.sourceId,
        destinations,
      });
      setPlan(p);
    } catch (err) {
      setPlanError(err instanceof Error ? err.message : String(err));
    } finally {
      setBuilding(false);
    }
  };

  const execute = async () => {
    // Explicit user action driving the durable offload flow: create the
    // session, add the reviewed destinations, adopt the source, and
    // create the offload job. No optimistic success — the UI reflects
    // the sidecar result and hands off to Activity.
    if (!planReviewable(plan) || !source || !projectId) {
      setExecuteError('The plan must be reviewable before execution.');
      return;
    }
    setExecuteError(null);
    setExecuting(true);
    try {
      const session = await window.mediaMate.intake.createSession({
        projectId,
        sourceId: source.sourceId,
        kind: 'offload',
      });
      for (const dest of [
        workingRoot ? { kind: 'working' as const, rootPath: workingRoot } : null,
        backupRoot ? { kind: 'backup' as const, rootPath: backupRoot } : null,
      ]) {
        if (dest) {
          await window.mediaMate.intake.addDestination({
            intakeSessionId: session.id,
            kind: dest.kind,
            rootPath: dest.rootPath,
          });
        }
      }
      // Adopt the source into the project so the offload has assets to
      // verify; the destination root is the working root.
      const adopted = await window.mediaMate.intake.adoptSource({
        sessionId: session.id,
        sourceId: source.sourceId,
        entries: source.entries,
        destinationRoot: workingRoot ?? '',
        projectId,
      });
      await window.mediaMate.job.create({
        projectId,
        command: 'offload',
        sessionId: session.id,
        totalSteps: adopted.assetIds.length,
      });
      setExecuted(true);
    } catch (err) {
      setExecuteError(err instanceof Error ? err.message : String(err));
    } finally {
      setExecuting(false);
    }
  };

  const stage = ingestStage({
    source,
    plan,
    executing,
    done: executed,
  });

  return (
    <div className="stack">
      <h2>Ingest</h2>
      <p className="muted">Stage: {stage}</p>

      <Panel title="1 · Source">
        <div className="row">
          <button className="btn" onClick={pickSource}>
            Choose source folder
          </button>
          <span className="muted grow">{sourcePath ?? 'none selected'}</span>
        </div>
        {sourcePath ? (
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn btn--primary" onClick={inspect} disabled={inspecting}>
              {inspecting ? 'Scanning…' : 'Scan source'}
            </button>
          </div>
        ) : null}
        {inspectError !== null ? <Chip tone="danger">{inspectError}</Chip> : null}
        {source && sourceReady(source) ? (
          <p className="muted" style={{ marginTop: 8 }}>
            {source.fileCount} files · {formatBytes(source.totalBytes)} · manifest{' '}
            {source.manifestHash.slice(0, 8)}
          </p>
        ) : null}
      </Panel>

      <Panel title="2 · Project & destinations">
        <Field label="Project">
          <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">Select a project…</option>
            {(projects.data?.projects ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="row">
          <button className="btn" onClick={pickWorking} disabled={!source}>
            Choose working root
          </button>
          <span className="muted grow">{workingRoot ?? 'none'}</span>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn" onClick={pickBackup} disabled={!source}>
            Choose backup root
          </button>
          <span className="muted grow">{backupRoot ?? 'none'}</span>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button
            className="btn btn--primary"
            onClick={buildPlan}
            disabled={!source || !projectId || (!workingRoot && !backupRoot) || building}
          >
            {building ? 'Building plan…' : 'Build plan'}
          </button>
        </div>
        {planError !== null ? <Chip tone="danger">{planError}</Chip> : null}
      </Panel>

      <Panel title="3 · Review plan">
        {plan === null ? (
          <p className="muted">Build a plan to review it.</p>
        ) : (
          <>
            <p>
              <Chip tone={plan.capacityOk ? 'ok' : 'danger'}>{capacityLabel(plan)}</Chip>{' '}
              <span className="muted">
                {plan.entries.length} files · {formatBytes(plan.totalBytes)}
              </span>
            </p>
            {plan.collisions.length > 0 ? (
              <p>
                <Chip tone="danger">
                  {plan.collisions.length} collision group(s) — review required
                </Chip>
              </p>
            ) : null}
            <div style={{ maxHeight: 200, overflowY: 'auto', marginTop: 8 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Dest</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.entries.slice(0, 100).map((e) => (
                    <tr key={e.relPath}>
                      <td className="muted">{e.relPath}</td>
                      <td className="muted">{e.destPath}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {plan.entries.length > 100 ? (
                <p className="muted">…and {plan.entries.length - 100} more</p>
              ) : null}
            </div>
          </>
        )}
      </Panel>

      <Panel title="4 · Execute">
        <p className="muted">
          Executing creates a durable offload job for the reviewed plan. It is not run until you
          confirm; the result is verified by the sidecar and shown in Activity.
        </p>
        <button
          className="btn btn--primary"
          onClick={execute}
          disabled={!planReviewable(plan) || planBlocked(plan) || executed || executing}
        >
          {executing ? 'Creating job…' : executed ? 'Offload job created' : 'Create offload job'}
        </button>
        {executeError !== null ? <Chip tone="danger">{executeError}</Chip> : null}
        {executed ? (
          <p>
            <Chip tone="ok">Job handed to Activity</Chip>
          </p>
        ) : null}
      </Panel>
    </div>
  );
}
