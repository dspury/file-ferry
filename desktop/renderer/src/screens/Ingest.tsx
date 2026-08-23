/**
 * Offload screen.
 *
 * Camera-card offload following plan -> review -> execute -> verify ->
 * receipt (plan §4.2). This screen drives source pick/inspect, project
 * + destination selection, plan build, and reviewable plan. Execution is
 * deliberately a separate, explicit action (create job) — never an
 * optimistic success; the stage gates on real plan data.
 */
import { useState } from 'react';
import { useAsync } from '../hooks/useAsync.js';
import {
  Banner,
  Chip,
  EmptyState,
  Field,
  Panel,
  PathCell,
  PathPicker,
  Steps,
  type StepDef,
} from '../components/ui.js';
import {
  ingestStage,
  ingestPrimary,
  planReviewable,
  planBlocked,
  sourceReady,
  capacityLabel,
  formatBytes,
} from '../lib/ingest.js';
import { navigateTo } from '../views.js';
import type { IntakePlan, SourceInspectResult } from '../../../shared/ipc-methods.js';

/** How many plan rows to render before deferring to a summary line. A plan
 *  row is one *write* -- a file copied to a working root and a backup is two
 *  rows -- so the count runs to tens of thousands. The review only needs a
 *  sample plus the totals, which are shown above the table. */
const PLAN_PREVIEW_ROWS = 100;

/*
 * The rail mirrors `ingestStage` exactly. Keeping the ids equal to the
 * stage strings means the two cannot drift: the screen never decides which
 * step is current, it just hands the stage over.
 */
const STEPS: readonly StepDef[] = [
  { id: 'source', label: 'Source' },
  { id: 'destinations', label: 'Destinations' },
  { id: 'plan', label: 'Plan' },
  { id: 'ready', label: 'Review' },
  // Everything above this reads and plans; from here ferry writes. The rail
  // draws the boundary so which side of it you are on is not something to be
  // inferred from the stage names.
  { id: 'running', label: 'Execute', writes: true },
  { id: 'done', label: 'Done' },
];

export function Ingest(): JSX.Element {
  const projects = useAsync(() => window.ferry.project.list());

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
    const result = await window.ferry.dialog.pick({ kind: 'directory' });
    if (!result.cancelled && result.path) setSourcePath(result.path);
  };

  const inspect = async () => {
    if (!sourcePath) return;
    setInspecting(true);
    setInspectError(null);
    setSource(null);
    try {
      const s = await window.ferry.source.inspect({ path: sourcePath, kind: 'card' });
      setSource(s);
    } catch (err) {
      setInspectError(err instanceof Error ? err.message : String(err));
    } finally {
      setInspecting(false);
    }
  };

  const pickWorking = async () => {
    const r = await window.ferry.dialog.pick({ kind: 'directory' });
    if (!r.cancelled && r.path) setWorkingRoot(r.path);
  };

  const pickBackup = async () => {
    const r = await window.ferry.dialog.pick({ kind: 'directory' });
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
      const p = await window.ferry.plan.build({
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
      const session = await window.ferry.intake.createSession({
        projectId,
        sourceId: source.sourceId,
        kind: 'offload',
      });
      for (const dest of [
        workingRoot ? { kind: 'working' as const, rootPath: workingRoot } : null,
        backupRoot ? { kind: 'backup' as const, rootPath: backupRoot } : null,
      ]) {
        if (dest) {
          await window.ferry.intake.addDestination({
            intakeSessionId: session.id,
            kind: dest.kind,
            rootPath: dest.rootPath,
          });
        }
      }
      // Adopt the source into the project so the offload has assets to
      // verify; the destination root is the working root.
      const adopted = await window.ferry.intake.adoptSource({
        sessionId: session.id,
        sourceId: source.sourceId,
        entries: source.entries,
        destinationRoot: workingRoot ?? '',
        projectId,
      });
      // `reviewed` is what actually starts the transfer. Creating a job
      // leaves it `planned`, waiting at the §6.4 review gate -- and this
      // screen *is* the review, so Execute means approved. Without it the
      // button reported success and nothing ever copied a byte.
      await window.ferry.job.create({
        projectId,
        command: 'offload',
        sessionId: session.id,
        totalSteps: adopted.assetIds.length,
        reviewed: true,
      });
      setExecuted(true);
    } catch (err) {
      setExecuteError(err instanceof Error ? err.message : String(err));
    } finally {
      setExecuting(false);
    }
  };

  const stage = ingestStage({ source, plan, executing, done: executed });
  const primary = ingestPrimary(stage);
  const projectList = projects.data?.projects ?? [];
  const hidden = plan === null ? 0 : Math.max(0, plan.entries.length - PLAN_PREVIEW_ROWS);

  return (
    <div className="page">
      {/*
        The outcome goes at the top of the page, above the rail, for the same
        reason it does on Organize: it was at the bottom of the panel that
        produced it, 1152px and 1198px down a 1260px page, so the two
        sentences an operator most needs after pressing Execute were below
        the fold at both 1280x800 and 1440x900 while the rail said DONE.

        The second of them is the one that matters: `DONE` at the top of a
        screen at the end of a card pull is the moment somebody reaches for
        the format button, and "keep the card" is the sentence that stops
        them. It now sits above the stage that says DONE rather than half a
        page below it. The rail keeps that word because there is nothing
        partial to report here -- `executed` is set only by a sidecar-
        confirmed job creation, and any failure leaves it false and banners
        the error -- and because what the stage means, handed off rather than
        finished, is precisely what these two banners now spell out first.
      */}
      {executed ? (
        <div className="stack">
          <Banner tone="ok" label="Handed off">
            The job is queued. Activity shows its progress, and the receipt when it finishes.
          </Banner>
          <Banner tone="warn" label="Keep the card">
            Do not format or erase the source card yet. Nothing has been verified: the receipt in
            Activity is what confirms every file landed and matched its checksum, and that is what
            makes the card safe to format.
          </Banner>
        </div>
      ) : null}

      <Steps label="Offload progress" steps={STEPS} activeId={stage} />

      <Panel
        title="Source"
        description="A camera card or any folder to copy from. Reading it never modifies it."
      >
        <Field label="Source folder">
          <PathPicker value={sourcePath} onPick={pickSource} buttonLabel="Browse…" />
        </Field>
        <div className="row">
          {/*
            Filled accent only while the scan is what comes next. Afterwards
            it is a real but secondary action -- the card has been swapped,
            or a file was added -- so it keeps the outline variant and stays
            enabled. Reading a source never modifies it, so there is nothing
            to protect the operator from by disabling it.
          */}
          <button
            type="button"
            className={primary === 'scan' ? 'btn btn--primary' : 'btn'}
            onClick={inspect}
            disabled={!sourcePath || inspecting}
          >
            {inspecting ? 'Scanning…' : 'Scan source'}
          </button>
          {source && sourceReady(source) ? (
            <span className="muted">
              {source.fileCount.toLocaleString()} files · {formatBytes(source.totalBytes)} ·
              manifest <code>{source.manifestHash.slice(0, 8)}</code>
            </span>
          ) : null}
        </div>
        {inspectError !== null ? <Banner tone="danger">{inspectError}</Banner> : null}
      </Panel>

      <Panel
        title="Project & destinations"
        description="At least one destination is required. A backup root gives you a second verified copy."
      >
        <Field label="Project">
          <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">Select a project…</option>
            {projectList.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="field-grid">
          <Field label="Working root" hint="Where you will edit from">
            <PathPicker
              value={workingRoot}
              onPick={pickWorking}
              disabled={!source}
              buttonLabel="Browse…"
            />
          </Field>
          <Field label="Backup root" hint="Optional second copy">
            <PathPicker
              value={backupRoot}
              onPick={pickBackup}
              disabled={!source}
              buttonLabel="Browse…"
            />
          </Field>
        </div>
        <div className="form-actions">
          <button
            type="button"
            className={primary === 'plan' ? 'btn btn--primary' : 'btn'}
            onClick={buildPlan}
            disabled={!source || !projectId || (!workingRoot && !backupRoot) || building}
          >
            {building ? 'Building plan…' : 'Build plan'}
          </button>
        </div>
        {planError !== null ? <Banner tone="danger">{planError}</Banner> : null}
      </Panel>

      <Panel
        title="Review plan"
        description="Nothing has been copied yet. This is exactly what will happen."
        flush={plan !== null}
        actions={
          plan === null ? undefined : (
            <>
              <Chip tone={plan.capacityOk ? 'ok' : 'danger'}>{capacityLabel(plan)}</Chip>
              <span className="muted">
                {plan.entries.length.toLocaleString()} copies · {formatBytes(plan.totalBytes)}
              </span>
            </>
          )
        }
      >
        {plan !== null && !plan.capacityOk ? (
          <div className="card__body">
            {/*
              `planBlocked` disables Execute on exactly this condition, and
              the only account of it was a three-word chip in the panel
              header. A blocked action has to say what is blocking it and
              what would clear it.
            */}
            <Banner tone="danger" label="Not enough room">
              The destination is short by {formatBytes(plan.neededBytes)}. Execute stays disabled
              until it fits — free space on the destination volume, or choose a different root.
            </Banner>
          </div>
        ) : null}
        {plan === null ? (
          <EmptyState
            message="No plan yet"
            hint="Scan a source above, pick a project and at least one destination, then build a plan. Nothing is written until you review it here and execute."
          />
        ) : (
          <>
            {plan.collisions.length > 0 ? (
              <div className="card__body">
                <Banner tone="danger" label="Collisions">
                  {plan.collisions.length} group(s) below would land on paths that already hold a
                  file. Check the destination rows before executing — an existing file at a planned
                  destination is the one case where an offload can cost you footage you already had.
                </Banner>
              </div>
            ) : null}
            <div className="table-wrap table-wrap--short">
              <table className="table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Destination</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.entries.slice(0, PLAN_PREVIEW_ROWS).map((e) => (
                    <tr key={e.relPath}>
                      <td>
                        <PathCell path={e.relPath} />
                      </td>
                      <td>
                        <PathCell path={e.destPath} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {hidden > 0 ? (
              <div className="card__footer muted">
                Showing the first {PLAN_PREVIEW_ROWS} of {plan.entries.length.toLocaleString()}{' '}
                files · {hidden.toLocaleString()} more not listed
              </div>
            ) : null}
          </>
        )}
      </Panel>

      <Panel
        title="Execute"
        description="Creates a durable offload job for the reviewed plan. The sidecar verifies the result; progress appears in Activity."
      >
        <div className="row">
          <button
            type="button"
            className={primary === 'execute' ? 'btn btn--primary' : 'btn'}
            onClick={execute}
            disabled={!planReviewable(plan) || planBlocked(plan) || executed || executing}
          >
            {executing ? 'Creating job…' : executed ? 'Offload job created' : 'Create offload job'}
          </button>
          {/*
            Once the job exists this is the next action, and the accent moves
            to it: watching the transfer is what turns a queued job into a
            receipt, and the receipt is what makes the card safe to format.
          */}
          {executed ? (
            <button
              type="button"
              className={primary === 'watch' ? 'btn btn--primary' : 'btn'}
              onClick={() => navigateTo('activity')}
            >
              Watch in Activity
            </button>
          ) : null}
        </div>
        {executeError !== null ? <Banner tone="danger">{executeError}</Banner> : null}
      </Panel>
    </div>
  );
}
