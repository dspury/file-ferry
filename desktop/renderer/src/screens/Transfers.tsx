/**
 * Transfers screen — the durable engine's pipeline (P6/B3).
 *
 * Scan -> plan -> review -> preflight -> approve -> verified copy ->
 * receipt, against the same `ApplicationService` the CLI drives. The
 * server owns every gate (approval needs a current passing preflight; a
 * moved fingerprint is refused; `needs_review` blocks approval). The
 * screen renders those gates and never works around them: Start stays
 * disabled until the exact plan in view is approved, and a decision that
 * supersedes a plan un-approves it in the same breath.
 *
 * Everything the screen needs to restore itself lives in the route hash
 * (`#/transfers?inv=…&dest=…&plan=…&pre=…&job=…`), so closing and
 * reopening the view — or reloading — cannot lose a scan, a plan, an
 * in-flight preflight, or a running job. The durable state itself lives
 * in the sidecar; the hash only remembers which ids to look at.
 */
import { useEffect, useRef, useState, type JSX } from 'react';
import { useAsync } from '../hooks/useAsync.js';
import { useJobStream } from '../hooks/useJobStream.js';
import { navigateTo } from '../views.js';
import { useRoute } from '../hooks/useRoute.js';
import {
  Banner,
  Chip,
  EmptyState,
  Field,
  LoadingState,
  Panel,
  PathPicker,
  Progress,
  ScreenError,
  ScreenLoading,
  StatCard,
  Steps,
} from '../components/ui.js';
import {
  inventoryStatusTone,
  isDecisionPending,
  planStatusTone,
  preflightStatusTone,
  receiptEntries,
  receiptStateTone,
  receiptSummary,
  startGate,
} from '../lib/transfers.js';
import { jobMeterStatus, jobStateTone } from '../lib/job-state.js';
import { progressLabel, snapshotProgress } from '../lib/activity.js';
import { formatBytes } from '../lib/doctor.js';
import type {
  DestinationResolution,
  JobDetail,
  PlanDecision,
  JobSnapshot,
  PreflightStatus,
  TransferPlanEntry,
  TransferPlanStatus,
  TransferReceiptStatus,
} from '../../../shared/ipc-methods.js';

/** Pipeline steps; `writes` marks the first stage that touches the disk. */
const STEPS = [
  { id: 'scan', label: 'Scan', writes: false },
  { id: 'plan', label: 'Plan', writes: false },
  { id: 'review', label: 'Review', writes: false },
  { id: 'preflight', label: 'Preflight', writes: false },
  { id: 'approve', label: 'Approve', writes: false },
  { id: 'transfer', label: 'Transfer', writes: true },
  { id: 'receipt', label: 'Receipt', writes: false },
] as const;

const ENTRY_PAGE = 100;
const RECEIPT_ROW_LIMIT = 200;
const TERMINAL_JOB_STATES = new Set(['succeeded', 'failed', 'cancelled', 'needs_attention']);

function idsFromHash(raw: string | null): readonly number[] {
  if (raw === null || raw === '') return [];
  return raw
    .split(',')
    .map((s) => Number(s))
    .filter((n) => Number.isInteger(n) && n > 0);
}

type SetParam = (patch: Readonly<Record<string, string | null>>) => void;

/** Set route params, dropping the ones a patch explicitly nulls. */
function routePatcher(params: ReadonlyMap<string, string>): SetParam {
  return (patch) => {
    const next: Record<string, string> = {};
    for (const [key, value] of params) next[key] = value;
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) delete next[key];
      else next[key] = value;
    }
    navigateTo('transfers', next);
  };
}

/** Reload on an interval while something is in flight sidecar-side. */
function useReloadWhile(active: boolean, reload: () => void, intervalMs = 500): void {
  const reloadRef = useRef(reload);
  // Same ref-tracking pattern `useJobStream` documents: this effect has no
  // dependency array on purpose, so the ref always holds the latest
  // committed reload and the interval never fires a stale closure.
  useEffect(() => {
    reloadRef.current = reload;
  });
  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(() => reloadRef.current(), intervalMs);
    return () => window.clearInterval(timer);
  }, [active, intervalMs]);
}

export function Transfers(): JSX.Element {
  const route = useRoute('transfers');
  const setParam = routePatcher(route.params);

  const inventoryIds = idsFromHash(route.params.get('inv') ?? null);
  const planId = route.params.get('plan') ?? null;
  const jobId = route.params.get('job') ?? null;

  const activeStep = jobId !== null ? 'transfer' : planId !== null ? 'plan' : 'scan';

  return (
    <div className="page">
      <Steps label="Transfer pipeline" steps={STEPS} activeId={activeStep} />
      <SourcesPanel inventoryIds={inventoryIds} setParam={setParam} />
      {inventoryIds.length > 0 && (
        <PlanSection
          inventoryIds={inventoryIds}
          planId={planId}
          jobId={jobId}
          setParam={setParam}
        />
      )}
    </div>
  );
}

// ---- scan -----------------------------------------------------------------

function SourcesPanel({
  inventoryIds,
  setParam,
}: {
  inventoryIds: readonly number[];
  setParam: SetParam;
}): JSX.Element {
  const statuses = useAsync(
    async () => Promise.all(inventoryIds.map((id) => window.ferry.inventory.status(id))),
    [inventoryIds.join(',')],
  );
  const scanning = (statuses.data ?? []).some((s) => s.status === 'scanning');
  useReloadWhile(scanning, statuses.reload);

  const [sourcePath, setSourcePath] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);

  const pick = async (): Promise<void> => {
    const result = await window.ferry.dialog.pick({ kind: 'directory' });
    if (!result.cancelled && result.path) setSourcePath(result.path);
  };

  const scan = async (): Promise<void> => {
    if (sourcePath === null) return;
    setStarting(true);
    setScanError(null);
    try {
      const created = await window.ferry.inventory.create({
        path: sourcePath,
        label: sourcePath.split('/').pop() ?? sourcePath,
      });
      // Record the id immediately: a reload mid-scan must find it.
      setParam({ inv: [...inventoryIds, created.inventoryId].join(',') });
      setSourcePath(null);
    } catch (err) {
      setScanError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  };

  return (
    <Panel
      title="Sources"
      description="Every folder is scanned read-only before anything is planned."
      flush
    >
      <div className="card__body stack">
        <div className="field-grid">
          <Field label="Source folder">
            <PathPicker value={sourcePath} onPick={pick} buttonLabel="Browse…" />
          </Field>
        </div>
        <div className="row">
          <button
            type="button"
            className="btn btn--primary"
            disabled={sourcePath === null || starting}
            onClick={scan}
          >
            {starting ? 'Starting scan…' : 'Scan source'}
          </button>
          {scanError !== null && <span className="muted">{scanError}</span>}
        </div>
      </div>

      {inventoryIds.length > 0 && (
        <div className="table-wrap">
          <table className="table" aria-label="Source inventories">
            <thead>
              <tr>
                <th>Root</th>
                <th>Status</th>
                <th>Counts</th>
                <th>Bytes</th>
                <th>Read errors</th>
              </tr>
            </thead>
            <tbody>
              {(statuses.data ?? []).map((s) => (
                <tr key={s.id}>
                  <td>
                    <span className="cell-path">{s.rootPath}</span>
                  </td>
                  <td>
                    <Chip tone={inventoryStatusTone(s.status)}>{s.status}</Chip>
                    {s.error !== null && <span className="muted">{` — ${s.error}`}</span>}
                  </td>
                  <td className="cell-num">{`${s.fileCount} file(s), ${s.dirCount} dir(s)`}</td>
                  <td className="cell-num">{formatBytes(s.totalBytes)}</td>
                  <td className="cell-num">{s.errorCount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {statuses.error !== null && <Banner tone="danger">{statuses.error}</Banner>}
      {scanning && (
        <div className="card__body">
          <LoadingState message="Scanning…" hint="Read-only; nothing is written." />
        </div>
      )}
    </Panel>
  );
}

// ---- destination + plan creation ------------------------------------------

function PlanSection({
  inventoryIds,
  planId,
  jobId,
  setParam,
}: {
  inventoryIds: readonly number[];
  planId: string | null;
  jobId: string | null;
  setParam: SetParam;
}): JSX.Element {
  const destinations = useAsync(async () => {
    const [list, resolve] = await Promise.all([
      window.ferry.destination.list(),
      window.ferry.destination.resolve(),
    ]);
    return { destinations: list.destinations, resolutions: resolve.resolutions };
  });
  const [destinationId, setDestinationId] = useState<number | null>(null);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [superseded, setSuperseded] = useState<string | null>(null);

  const all = destinations.data?.destinations ?? [];
  const resolutionOf = (id: number): DestinationResolution | undefined =>
    destinations.data?.resolutions.find((r) => r.destinationId === id);

  const createPlan = async (): Promise<void> => {
    if (destinationId === null) return;
    setPlanning(true);
    setPlanError(null);
    try {
      const plan = await window.ferry.transfer.planCreate({
        destinationId,
        inventoryIds: [...inventoryIds],
      });
      setSuperseded(null);
      setParam({ plan: plan.id, pre: null, job: null });
    } catch (err) {
      setPlanError(err instanceof Error ? err.message : String(err));
    } finally {
      setPlanning(false);
    }
  };

  const replacePlan = (note: string, nextPlanId: string): void => {
    setSuperseded(note);
    // A decision produces a new plan; the old preflight and any approval
    // belong to the plan that was replaced.
    setParam({ plan: nextPlanId, pre: null, job: null });
  };

  return (
    <>
      <Panel
        title="Destination"
        description="Only destinations resolving as available right now are offered; preflight re-checks at approval time."
      >
        <div className="stack">
          {all.length === 0 ? (
            <EmptyState
              density="compact"
              message="No saved destinations"
              hint="Save one in Destinations, or connect the volume it points at."
            />
          ) : (
            <div className="row" role="radiogroup" aria-label="Destination">
              {all.map((d) => {
                const r = resolutionOf(d.id);
                return (
                  <button
                    key={d.id}
                    type="button"
                    className={`btn btn--sm${d.id === destinationId ? ' btn--primary' : ''}`}
                    aria-pressed={d.id === destinationId}
                    disabled={r === undefined || r.status !== 'available'}
                    title={r?.reason ?? ''}
                    onClick={() => setDestinationId(d.id)}
                  >
                    {`${d.name} · ${r?.status ?? 'unknown'}`}
                  </button>
                );
              })}
            </div>
          )}
          <div className="row">
            <button
              type="button"
              className="btn btn--primary"
              disabled={destinationId === null || planning}
              onClick={createPlan}
            >
              {planning ? 'Planning…' : 'Create plan'}
            </button>
            {planError !== null && <span className="muted">{planError}</span>}
          </div>
        </div>
      </Panel>

      {superseded !== null && (
        <Banner tone="attention" label="Plan superseded">
          {`${superseded} Its approval no longer counts; review and approve the new plan.`}
        </Banner>
      )}

      {planId !== null && (
        <PlanPipeline
          planId={planId}
          jobId={jobId}
          setParam={setParam}
          onSuperseded={replacePlan}
        />
      )}
    </>
  );
}

// ---- the plan pipeline -----------------------------------------------------

function PlanPipeline({
  planId,
  jobId,
  setParam,
  onSuperseded,
}: {
  planId: string;
  jobId: string | null;
  setParam: SetParam;
  onSuperseded: (note: string, nextPlanId: string) => void;
}): JSX.Element {
  const plan = useAsync(() => window.ferry.transfer.planGet(planId), [planId]);
  if (plan.loading && plan.data === null) {
    return <ScreenLoading message="Reading plan…" />;
  }
  if (plan.error !== null) {
    return <ScreenError message={plan.error} onRetry={plan.reload} />;
  }
  if (plan.data === null) {
    return <ScreenError message="The plan could not be read." onRetry={plan.reload} />;
  }
  // The inner component exists so the preflight hook below has a stable
  // hook order: the checks above return before any hook beyond `useAsync`
  // runs, and an early return after hooks would change that.
  return (
    <PlanBody
      planId={planId}
      jobId={jobId}
      setParam={setParam}
      onSuperseded={onSuperseded}
      planStatus={plan.data}
      reloadPlan={plan.reload}
    />
  );
}

function PlanBody({
  planId,
  jobId,
  setParam,
  onSuperseded,
  planStatus,
  reloadPlan,
}: {
  planId: string;
  jobId: string | null;
  setParam: SetParam;
  onSuperseded: (note: string, nextPlanId: string) => void;
  planStatus: TransferPlanStatus;
  reloadPlan: () => void;
}): JSX.Element {
  const gate = startGate(planStatus);
  const executed = planStatus.status === 'executed';
  // Preflight state must be readable by the approve stage too: approval
  // requires a current passing preflight for the exact fingerprint. The
  // server refuses without one and hands over the reason; the disabled
  // button here exists so the UI says so *before* the click, not instead
  // of the server's answer.
  const preflight = usePreflight(planId, planStatus.fingerprint);
  return (
    <>
      <PlanPanel plan={planStatus} />
      {!executed && <EntriesPanel planId={planId} onSuperseded={onSuperseded} />}
      {!executed && <PreflightPanel preflight={preflight} />}
      {!executed && (
        <ApprovalPanel plan={planStatus} preflight={preflight} onApproved={reloadPlan} />
      )}
      {!executed && (
        <ExecutionPanel
          planId={planId}
          jobId={jobId}
          plan={planStatus}
          setParam={setParam}
          canStart={gate.canStart}
          gateReason={gate.reason}
        />
      )}
      {executed && <ReceiptPanel planId={planId} />}
      {!executed && jobId !== null && <ReceiptPanel planId={planId} />}
    </>
  );
}

function PlanPanel({ plan }: { plan: TransferPlanStatus }): JSX.Element {
  return (
    <Panel
      title="Plan"
      description="A plan is immutable: decisions produce a new revision, and this one is left exactly as it was."
      actions={<Chip tone={planStatusTone(plan.status)}>{plan.status}</Chip>}
    >
      <div className="stack">
        <div className="stats">
          <StatCard label="Files" value={plan.totalFiles} />
          <StatCard label="Bytes" value={formatBytes(plan.totalBytes)} />
          <StatCard
            label="Conflicts"
            value={plan.conflictCount}
            tone={plan.conflictCount > 0 ? 'attention' : 'neutral'}
          />
          <StatCard
            label="Blocking review"
            value={plan.blockingCount}
            tone={plan.blockingCount > 0 ? 'danger' : 'neutral'}
          />
        </div>
        <p className="mono">{`fingerprint ${plan.fingerprint.slice(0, 16)}`}</p>
        <p className="muted">{`writes under ${plan.destinationBindingPath}`}</p>
        <p className="muted">
          {plan.capacityUnknown
            ? 'Capacity unknown — the destination volume did not report free space.'
            : `${formatBytes(plan.freeBytes ?? 0)} free, ${formatBytes(plan.neededBytes)} needed${
                plan.capacityOk ? '' : ' — short of space'
              }`}
        </p>
        {plan.warnings.map((w) => (
          <Banner key={w} tone="warn" label="Plan warning">
            {w}
          </Banner>
        ))}
        {plan.presetReviewRequired.length > 0 && (
          <Banner tone="attention" label="Preset needs a decision">
            {`The pinned preset revision still needs a decision about: ${plan.presetReviewRequired.join(', ')}.`}
          </Banner>
        )}
      </div>
    </Panel>
  );
}

// ---- entries + decisions ---------------------------------------------------

function EntriesPanel({
  planId,
  onSuperseded,
}: {
  planId: string;
  onSuperseded: (note: string, nextPlanId: string) => void;
}): JSX.Element {
  const [after, setAfter] = useState(0);
  const page = useAsync(
    () => window.ferry.transfer.planEntries(planId, { limit: ENTRY_PAGE, after }),
    [planId, after],
  );
  const [busyId, setBusyId] = useState<number | null>(null);
  const [decideError, setDecideError] = useState<string | null>(null);

  const entries = page.data?.entries ?? [];
  const remaining = page.data === null ? 0 : Math.max(0, page.data.total - entries.length);

  // Server-side: entry ids alone resolve as `exclude`; skip-if-identical is
  // an explicit decision keyed by (inventory, relPath) — the stable key a
  // decision has to survive the entry-id renumbering a new revision causes.
  const decide = async (
    entry: TransferPlanEntry,
    action: 'exclude' | 'skip_identical',
  ): Promise<void> => {
    setBusyId(entry.id);
    setDecideError(null);
    try {
      const decision: PlanDecision = {
        inventoryId: entry.inventoryId ?? 0,
        relPath: entry.relPath,
        action,
      };
      const next = await window.ferry.transfer.planResolve({
        id: planId,
        entryIds: [],
        decisions: [decision],
      });
      onSuperseded(`Deciding entry ${entry.id} produced plan ${next.id.slice(0, 8)}…`, next.id);
    } catch (err) {
      setDecideError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Panel
      title="Entries"
      description="Every mapping, in full — paged, so first-page rendering is never mistaken for the inventory."
      actions={
        page.data !== null && page.data.nextCursor !== null ? (
          <button
            type="button"
            className="btn btn--sm"
            onClick={() => setAfter(page.data!.nextCursor!)}
          >
            {`Load ${Math.min(ENTRY_PAGE, remaining)} more`}
          </button>
        ) : null
      }
      flush
    >
      <div className="card__body">
        {entries.length === 0 ? (
          <EmptyState
            density="compact"
            message="No entries"
            hint="Nothing was mapped — check the source scan and the destination."
          />
        ) : (
          <div className="table-wrap table-wrap--short">
            <table className="table" aria-label="Plan entries">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Destination</th>
                  <th>Action</th>
                  <th>Notes</th>
                  <th>Decision</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.id}>
                    <td>
                      <span className="cell-path">
                        {e.relPath === '' ? e.sourcePath : e.relPath}
                      </span>
                    </td>
                    <td>
                      <span className="cell-path">{e.destRelPath}</span>
                      {e.renamedFrom !== null && (
                        <span className="muted">{` (renamed from ${e.renamedFrom})`}</span>
                      )}
                    </td>
                    <td>
                      <Chip tone={entryTone(e.action)}>{e.action}</Chip>
                    </td>
                    <td>
                      {e.conflict ??
                        e.exclusionReason ??
                        (e.matchedRule !== null ? `rule ${e.matchedRule}` : '—')}
                      {e.excludedByUser && <span className="muted"> (your decision)</span>}
                    </td>
                    <td className="cell-actions">
                      {isDecisionPending(e) ? (
                        <div className="row">
                          <button
                            type="button"
                            className="btn btn--sm btn--danger"
                            disabled={busyId === e.id}
                            onClick={() => decide(e, 'exclude')}
                          >
                            Exclude
                          </button>
                          {e.action === 'needs_review' && (
                            <button
                              type="button"
                              className="btn btn--sm"
                              disabled={busyId === e.id}
                              onClick={() => decide(e, 'skip_identical')}
                            >
                              Skip if identical
                            </button>
                          )}
                        </div>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {decideError !== null && <Banner tone="danger">{decideError}</Banner>}
        {page.data !== null && page.data.nextCursor === null && (
          <p className="muted">{`All ${page.data.total} entries shown.`}</p>
        )}
      </div>
    </Panel>
  );
}

function entryTone(action: string): 'neutral' | 'ok' | 'attention' | 'danger' {
  switch (action) {
    case 'copy':
      return 'neutral';
    case 'skip_identical':
      return 'ok';
    case 'exclude':
      return 'ok';
    case 'needs_review':
      return 'attention';
    default:
      return 'neutral';
  }
}

// ---- preflight + approval ---------------------------------------------------

/** Preflight state for one plan, shared by the preflight and approve stages. */
interface PreflightState {
  readonly hasRun: boolean;
  readonly passed: boolean;
  readonly stale: boolean;
  readonly status: PreflightStatus | null;
  readonly starting: boolean;
  readonly run: () => void;
  readonly error: string | null;
}

function usePreflight(planId: string, planFingerprint: string): PreflightState {
  const [startedId, setStartedId] = useState<number | null>(null);
  const status = useAsync<PreflightStatus | null>(
    async () => (startedId === null ? null : window.ferry.transfer.preflightStatus(startedId)),
    [startedId],
  );
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useReloadWhile(status.data?.status === 'running', status.reload);

  const run = async (): Promise<void> => {
    setStarting(true);
    setError(null);
    try {
      const started = await window.ferry.transfer.preflightStart(planId);
      setStartedId(started.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  };

  const s = status.data ?? null;
  const current = s !== null && s.planId === planId;
  const stale = current && s.fingerprint !== planFingerprint;
  const passed = current && !stale && s.status === 'passed';
  return {
    hasRun: current,
    passed,
    stale,
    status: current ? s : null,
    starting,
    run: () => void run(),
    error,
  };
}

function PreflightPanel({ preflight }: { preflight: PreflightState }): JSX.Element {
  const s = preflight.status;
  return (
    <Panel
      title="Preflight"
      description="Validates the plan against the live filesystem and the mounted destination."
      actions={s !== null ? <Chip tone={preflightStatusTone(s.status)}>{s.status}</Chip> : null}
    >
      <div className="stack">
        {s === null ? (
          <p className="muted">No preflight has run for this plan yet.</p>
        ) : (
          <>
            {s.status === 'running' && (
              <Progress
                percent={
                  s.totalEntries > 0 ? Math.round((s.checkedEntries / s.totalEntries) * 100) : 0
                }
                label="Preflight checks"
              />
            )}
            {preflight.stale && (
              <Banner tone="attention" label="Preflight is stale">
                It ran against a different plan revision. Run it again before approving.
              </Banner>
            )}
            {s.status === 'failed' && s.findings.length > 0 && (
              <Banner tone="attention" label="Preflight findings">
                <ul className="stack">
                  {s.findings.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </Banner>
            )}
            {preflight.passed && (
              <Banner tone="ok" label="Preflight passed">
                {`Checked ${s.totalEntries} entries against the live filesystem.`}
              </Banner>
            )}
          </>
        )}
        <div className="row">
          <button
            type="button"
            className="btn"
            onClick={preflight.run}
            disabled={preflight.starting}
          >
            {preflight.starting
              ? 'Starting…'
              : s === null
                ? 'Run preflight'
                : 'Run preflight again'}
          </button>
        </div>
        {preflight.error !== null && <Banner tone="danger">{preflight.error}</Banner>}
      </div>
    </Panel>
  );
}

/**
 * The approve stage. The server owns the rule — a current passing
 * preflight for this exact fingerprint is part of `TransferPlanService.approve`
 * — so this panel does not reimplement it. It arms the control once
 * preflight has passed (saying so before the click), sends the plan's exact
 * fingerprint, and surfaces the server's refusal reason when one comes back.
 * Because a decision supersedes a plan and un-approves it, the control
 * re-arms automatically: the new revision renders with its own approval.
 */
function ApprovalPanel({
  plan,
  preflight,
  onApproved,
}: {
  plan: TransferPlanStatus;
  preflight: PreflightState;
  onApproved: () => void;
}): JSX.Element {
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const approvalCurrent = plan.approvedFingerprint === plan.fingerprint;
  const alreadyApproved = plan.status === 'approved' && approvalCurrent;
  const approvalStale = plan.status === 'approved' && !approvalCurrent;
  const armed = preflight.passed;
  const canApprove = armed && !alreadyApproved && !approving;

  const approve = async (): Promise<void> => {
    setApproving(true);
    setError(null);
    try {
      // The exact fingerprint of the plan in view — a past approval or a
      // newer revision's fingerprint is refused server-side either way.
      await window.ferry.transfer.planApprove(plan.id, plan.fingerprint);
      onApproved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApproving(false);
    }
  };

  return (
    <Panel
      title="Approve"
      description="Approval is recorded for the exact plan fingerprint shown above; a decision supersedes it."
      actions={alreadyApproved ? <Chip tone="ok">approved</Chip> : null}
    >
      <div className="stack">
        {alreadyApproved && (
          <Banner tone="ok" label="Approved">
            This exact revision is approved and ready to start.
          </Banner>
        )}
        {approvalStale && (
          <Banner tone="attention" label="Approval is stale">
            {`An approval exists for fingerprint ${plan.approvedFingerprint?.slice(0, 16)}…, not this revision. Approve again after preflight.`}
          </Banner>
        )}
        {!armed && !alreadyApproved && (
          <p className="muted">Approve arms once preflight passes for this revision.</p>
        )}
        {approvalStale && !armed && (
          <p className="muted">Run preflight again for the new revision, then approve.</p>
        )}
        <div className="row">
          <button
            type="button"
            className="btn btn--primary"
            disabled={!canApprove}
            title={armed ? undefined : 'Run preflight for this plan first'}
            onClick={() => void approve()}
          >
            {approving ? 'Approving…' : 'Approve plan'}
          </button>
        </div>
        {error !== null && (
          <Banner tone="attention" label="Cannot approve">
            {error}
          </Banner>
        )}
      </div>
    </Panel>
  );
}

// ---- execution -------------------------------------------------------------

function ExecutionPanel({
  planId,
  jobId,
  plan,
  setParam,
  canStart,
  gateReason,
}: {
  planId: string;
  jobId: string | null;
  plan: TransferPlanStatus;
  setParam: SetParam;
  canStart: boolean;
  gateReason: string | null;
}): JSX.Element {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const job = useAsync<JobDetail | null>(
    async () => (jobId === null ? null : window.ferry.job.get(jobId)),
    [jobId],
  );
  const jobDetail = job.data ?? null;
  const activeJob =
    jobDetail !== null && !TERMINAL_JOB_STATES.has(jobDetail.state) ? jobDetail : null;
  useReloadWhile(activeJob !== null, job.reload);

  const stream = useJobStream(activeJob === null ? [] : [activeJob], () => job.reload());
  const snapshot: JobSnapshot | null =
    activeJob === null ? null : (stream.snapshots.get(activeJob.id) ?? null);

  const start = async (): Promise<void> => {
    setStarting(true);
    setError(null);
    try {
      const started = await window.ferry.transfer.start(planId, plan.fingerprint);
      setParam({ job: started.job.id });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  };

  const cancel = async (): Promise<void> => {
    if (activeJob === null) return;
    await window.ferry.job.cancel(activeJob.id);
    job.reload();
  };

  const resume = async (): Promise<void> => {
    if (jobDetail === null) return;
    try {
      await window.ferry.job.resume(jobDetail.id);
      job.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const state = jobDetail?.state ?? null;
  const percent = snapshot === null ? 0 : Math.round(snapshotProgress(snapshot) * 100);
  const label = snapshot === null ? null : progressLabel(snapshot);

  return (
    <Panel
      title="Transfer"
      description="The copy is durable: closing this view or the app cannot lose it. Resume happens at a safe boundary."
      actions={state !== null ? <Chip tone={jobStateTone(state)}>{state}</Chip> : null}
    >
      <div className="stack">
        {!canStart && gateReason !== null && (
          <Banner tone="attention" label="Start is locked">
            {gateReason}
          </Banner>
        )}
        <div className="row">
          <button
            type="button"
            className="btn btn--primary"
            disabled={!canStart || starting || activeJob !== null}
            title={gateReason ?? undefined}
            onClick={start}
          >
            {starting ? 'Starting…' : 'Start verified transfer'}
          </button>
          {activeJob !== null && (
            <button type="button" className="btn" onClick={cancel}>
              Cancel
            </button>
          )}
          {(state === 'needs_attention' || state === 'resumable') && (
            <button type="button" className="btn" onClick={resume}>
              Resume
            </button>
          )}
        </div>
        {jobDetail !== null && (
          <>
            <Progress
              percent={percent}
              label="Transfer progress"
              status={jobMeterStatus(state ?? '')}
            />
            {label !== null && <p className="muted">{label}</p>}
            {jobDetail.error !== null && <Banner tone="danger">{jobDetail.error}</Banner>}
          </>
        )}
        {error !== null && <Banner tone="danger">{error}</Banner>}
      </div>
    </Panel>
  );
}

// ---- receipt ---------------------------------------------------------------

function ReceiptPanel({ planId }: { planId: string }): JSX.Element {
  const receipt = useAsync<TransferReceiptStatus | null>(async () => {
    try {
      return await window.ferry.transfer.receipt(planId);
    } catch (err) {
      // "no execution" is the honest answer before anything has run.
      if (String(err).includes('no execution')) return null;
      throw err;
    }
  }, [planId]);
  const [exportNote, setExportNote] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  if (receipt.loading && receipt.data === null) {
    return (
      <Panel title="Receipt" flush>
        <div className="card__body">
          <LoadingState message="Reading receipt…" />
        </div>
      </Panel>
    );
  }
  if (receipt.error !== null) {
    return <ScreenError message={receipt.error} onRetry={receipt.reload} />;
  }
  const r = receipt.data;
  if (r === null) {
    return (
      <Panel title="Receipt">
        <EmptyState
          density="compact"
          message="No receipt yet"
          hint="The receipt is written when an execution finishes; nothing is claimed before then."
        />
      </Panel>
    );
  }
  const summary = receiptSummary(r.receipt);
  const { rows, total } = receiptEntries(r.receipt, RECEIPT_ROW_LIMIT);

  const exportReceipt = async (): Promise<void> => {
    setExportError(null);
    try {
      const exported = await window.ferry.transfer.receiptExport(planId);
      setExportNote(exported.exportedPath ?? `export failed: ${exported.exportError ?? 'unknown'}`);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Panel
      title="Receipt"
      description="Written to the database before anything is claimed; the JSON export is retriable."
      actions={<Chip tone={receiptStateTone(r.finalState)}>{r.finalState}</Chip>}
    >
      <div className="stack">
        <div className="stats">
          <StatCard
            label="Committed"
            value={summary.committed ?? '—'}
            tone={receiptStateTone(r.finalState)}
          />
          <StatCard
            label="Failed"
            value={summary.failed ?? 0}
            tone={(summary.failed ?? 0) > 0 ? 'danger' : 'neutral'}
          />
          <StatCard label="Planned files" value={summary.expectedFiles ?? '—'} />
        </div>
        {r.exportError !== null && (
          <Banner tone="warn" label="Export failed">
            {`${r.exportError} — the receipt itself is safe; exporting can be retried.`}
          </Banner>
        )}
        {exportError !== null && <Banner tone="danger">{exportError}</Banner>}
        {exportNote !== null && (
          <Banner tone="ok" label="Export">
            {exportNote}
          </Banner>
        )}
        {summary.errors.length > 0 && (
          <Banner tone="attention" label="Recorded errors">
            <ul className="stack">
              {summary.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </Banner>
        )}
        <div className="row">
          <button type="button" className="btn" onClick={exportReceipt}>
            Export JSON
          </button>
        </div>
        <div className="table-wrap table-wrap--short">
          <table className="table" aria-label="Receipt entries">
            <thead>
              <tr>
                <th>State</th>
                <th>Destination path</th>
                <th>Size</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row.destRelPath}-${i}`}>
                  <td>
                    <Chip
                      tone={
                        row.state === 'committed'
                          ? 'ok'
                          : row.state === 'failed'
                            ? 'danger'
                            : 'neutral'
                      }
                    >
                      {row.state}
                    </Chip>
                  </td>
                  <td>
                    <span className="cell-path">{row.destRelPath}</span>
                  </td>
                  <td className="cell-num">{row.size === null ? '—' : formatBytes(row.size)}</td>
                  <td>{row.error ?? row.warning ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length < total && (
          <p className="muted">{`Showing the first ${rows.length} of ${total} entries; the full list is in the exported JSON.`}</p>
        )}
      </div>
    </Panel>
  );
}
