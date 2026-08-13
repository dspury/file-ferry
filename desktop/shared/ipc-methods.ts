/**
 * Typed method catalog for the IPC contract.
 *
 * The methods named here are the contract; both the TypeScript side
 * (desktop) and the pydantic side (sidecar) MUST implement them with
 * matching params and results. The plan §8.3 lists the full family;
 * the foundation package ships only the first cluster. New methods
 * are added by extending this map and updating the corresponding
 * pydantic models.
 *
 * The contract test (`tests/ipc-contract.test.ts`) round-trips every
 * method in this map through a pair of in-process transceivers.
 */
import type { ProtocolVersion } from './version.js';

export interface AppStatus {
  readonly sidecarVersion: string;
  readonly protocolVersion: ProtocolVersion;
  readonly capabilities: readonly string[];
}

export interface GetCapabilities {
  readonly methods: readonly string[];
  readonly events: readonly string[];
  readonly version: ProtocolVersion;
}

export interface StoragePolicy {
  readonly requiredReplicas: number;
  readonly backupOnDifferentVolume: boolean;
  readonly checksumAlgo: 'xxhash64' | 'sha256';
  readonly safetyReserveBytes: number;
  readonly requireSourceFingerprint: boolean;
}

export interface CreateProjectParams {
  readonly name: string;
  readonly workingRoot: string;
  readonly backupRoot: string;
  readonly storagePolicy?: StoragePolicy;
  readonly acknowledgeWeaker?: boolean;
}

export interface CreateProjectResult {
  readonly projectId: string;
}

export interface ProjectSummary {
  readonly id: string;
  readonly name: string;
  readonly workingRoot: string;
  readonly backupRoot: string | null;
  readonly status: string;
  readonly storagePolicy: StoragePolicy;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly archivedAt: string | null;
}

export interface ProjectDetail extends ProjectSummary {
  readonly organizationProfileId: number | null;
  readonly proxyDefaults: Record<string, unknown> | null;
  readonly resolveDefaults: Record<string, unknown> | null;
}

export interface UpdateProjectParams {
  readonly id: string;
  readonly name?: string;
  readonly workingRoot?: string;
  readonly backupRoot?: string;
  readonly storagePolicy?: StoragePolicy;
  readonly acknowledgeWeaker?: boolean;
}

export interface ArchiveProjectParams {
  readonly id: string;
}

export interface ListProjectsResult {
  readonly projects: readonly ProjectSummary[];
}

export interface SourceInventoryEntry {
  readonly path: string;
  readonly size: number;
  readonly mtime: number;
}

export interface SourceInspectParams {
  readonly path: string;
  readonly kind: 'card' | 'existing_media';
  readonly label?: string | null;
}

export interface SourceInspectResult {
  readonly sourceId: number;
  readonly rootPath: string;
  readonly kind: string;
  readonly label: string | null;
  readonly fileCount: number;
  readonly totalBytes: number;
  readonly manifestHash: string;
  readonly entries: readonly SourceInventoryEntry[];
}

export interface OrganizationProfile {
  readonly id: number;
  readonly name: string;
  readonly version: number;
  readonly template: Record<string, unknown>;
  readonly conflictPolicy: string;
  readonly mutationPolicy: string;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface SaveProfileParams {
  readonly name: string;
  readonly template: Record<string, unknown>;
  readonly conflictPolicy?: string;
  readonly mutationPolicy?: string;
}

export interface ListProfilesResult {
  readonly profiles: readonly OrganizationProfile[];
}

export interface AssetSummary {
  readonly id: string;
  readonly sourceId: number | null;
  readonly sourceRelativePath: string;
  readonly observedSize: number | null;
  readonly observedMtime: number | null;
  readonly lifecycleState: string;
  readonly mediaKind: string | null;
  readonly firstSeenAt: string;
}

export interface ListAssetsParams {
  readonly projectId?: string;
}

export interface ListAssetsResult {
  readonly assets: readonly AssetSummary[];
}

export interface ReplicaSummary {
  readonly id: number;
  readonly assetId: string;
  readonly projectId: string;
  readonly path: string;
  readonly checksum: string | null;
  readonly checksumAlgo: string | null;
  readonly verified: boolean;
  readonly verifiedAt: string | null;
  readonly availability: string;
}

export interface VerifyReplicaParams {
  readonly replicaId: number;
  readonly sourcePath: string;
  readonly checksumAlgo: string;
}

export interface VerifyReplicaResult {
  readonly replicaId: number;
  readonly verified: boolean;
  readonly checksumAlgo: string;
  readonly sourceChecksum: string;
  readonly replicaChecksum: string;
}

export interface ListReplicasResult {
  readonly replicas: readonly ReplicaSummary[];
}

export interface IntakeSession {
  readonly id: string;
  readonly projectId: string;
  readonly sourceId: number | null;
  readonly kind: string;
  readonly status: string;
  readonly safeToFormat: boolean;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface IntakeDestination {
  readonly id: number;
  readonly intakeSessionId: string;
  readonly kind: string;
  readonly rootPath: string;
  readonly role: string | null;
  readonly required: boolean;
  readonly verified: boolean;
}

export interface CreateIntakeSessionParams {
  readonly projectId: string;
  readonly sourceId: number;
  readonly kind: 'offload' | 'existing_folder';
}

export interface AddDestinationParams {
  readonly intakeSessionId: string;
  readonly kind: 'working' | 'backup' | 'organization';
  readonly rootPath: string;
  readonly role?: string | null;
  readonly required?: boolean;
}

export interface SafeToFormatEval {
  readonly sessionId: string;
  readonly safe: boolean;
  readonly unmet: readonly string[];
}

export interface JobDetail {
  readonly id: string;
  readonly projectId: string;
  readonly sessionId: string | null;
  readonly command: string;
  readonly state: string;
  readonly currentStep: string | null;
  readonly totalSteps: number;
  readonly startedAt: string | null;
  readonly updatedAt: string;
  readonly finishedAt: string | null;
  readonly error: string | null;
  readonly resumable: boolean;
}

export interface CreateJobParams {
  readonly projectId: string;
  readonly command: string;
  readonly argsFingerprint?: string | null;
  readonly sessionId?: string | null;
  readonly totalSteps?: number;
}

export interface JobTransitionParams {
  readonly id: string;
  readonly fromState: string;
  readonly toState: string;
}

export interface ListJobsResult {
  readonly jobs: readonly JobDetail[];
}

export interface AuditEvent {
  readonly id: number;
  readonly occurredAt: string;
  readonly eventType: string;
  readonly entityType: string | null;
  readonly entityId: string | null;
  readonly data: Record<string, unknown> | null;
  readonly runId: number | null;
}

export interface ListAuditParams {
  readonly entityId?: string;
  readonly limit?: number;
}

export interface ListAuditResult {
  readonly events: readonly AuditEvent[];
}

export interface PlanDestination {
  readonly kind: 'working' | 'backup' | 'organization';
  readonly rootPath: string;
  readonly required?: boolean;
}

export interface PlanEntry {
  readonly relPath: string;
  readonly destPath: string;
  readonly size: number;
}

export interface CollisionIssue {
  readonly path: string;
  readonly reason: string;
  readonly count: number;
}

export interface IntakePlan {
  readonly fingerprint: string;
  readonly projectId: string;
  readonly sourceId: number;
  readonly sourceRoot: string;
  readonly destinations: readonly PlanDestination[];
  readonly entries: readonly PlanEntry[];
  readonly totalBytes: number;
  readonly capacityOk: boolean;
  readonly neededBytes: number;
  readonly warnings: readonly string[];
  readonly collisions: readonly CollisionIssue[];
}

export interface BuildPlanParams {
  readonly projectId: string;
  readonly sourceId: number;
  readonly destinations: readonly PlanDestination[];
}

export interface ExportReceiptParams {
  readonly operationId: string;
  readonly format: 'markdown' | 'html';
}

export interface ExportReceiptResult {
  readonly content: string;
}

export interface CancelJobParams {
  readonly id: string;
}

export interface ReconcileEntry {
  readonly replicaId: number;
  readonly path: string;
  readonly availability: string;
  readonly status: string;
  readonly expectedChecksum: string | null;
  readonly actualChecksum: string | null;
}

export interface ReconcileReport {
  readonly assetId: string;
  readonly entries: readonly ReconcileEntry[];
}

export interface ReconcileAssetParams {
  readonly assetId: string;
  readonly checksumAlgo?: string;
}

export interface ReconcileProjectParams {
  readonly projectId: string;
  readonly checksumAlgo?: string;
}

export interface AcceptChangeParams {
  readonly assetId: string;
  readonly replicaId: number;
  readonly checksumAlgo: string;
}

export interface OrganizeEntry {
  readonly sourcePath: string;
  readonly destPath: string;
  readonly size: number;
}

export interface OrganizeOutcome {
  readonly sourcePath: string;
  readonly destPath: string;
  readonly operation: string;
  readonly ok: boolean;
  readonly error: string | null;
}

export interface OrganizePreview {
  readonly sourceRoot: string;
  readonly destRoot: string;
  readonly entries: readonly OrganizeEntry[];
  readonly collisions: readonly CollisionIssue[];
  readonly totalBytes: number;
  readonly mode: string;
}

export interface OrganizePreviewParams {
  readonly sourceRoot: string;
  readonly destRoot: string;
  readonly entries: readonly SourceInventoryEntry[];
  readonly template?: Record<string, unknown>;
  readonly mode?: 'copy' | 'move' | 'link';
}

export interface OrganizeApplyParams {
  readonly sourceRoot: string;
  readonly destRoot: string;
  readonly entries: readonly SourceInventoryEntry[];
  readonly mode?: 'copy' | 'move' | 'link';
  readonly confirmMove?: boolean;
  readonly template?: Record<string, unknown>;
}

export interface OrganizeResult {
  readonly entries: readonly OrganizeOutcome[];
}

export interface ClipMember {
  readonly assetId: string;
  readonly role: string;
}

export interface LogicalClip {
  readonly id: number;
  readonly sourceId: number;
  readonly clipName: string;
  readonly confidence: number;
  readonly resolved: boolean;
  readonly members: readonly ClipMember[];
}

export interface DetectClipsParams {
  readonly sourceId: number;
}

export interface DerivativeSummary {
  readonly id: number;
  readonly assetId: string;
  readonly kind: string;
  readonly outputPath: string;
  readonly settingsFingerprint: string | null;
  readonly status: string;
  readonly readiness: number;
}

export interface ManifestAsset {
  readonly id: string;
  readonly sourceRelativePath: string;
  readonly observedSize: number | null;
  readonly lifecycleState: string;
  readonly mediaKind: string | null;
}

export interface ManifestReplica {
  readonly assetId: string;
  readonly path: string;
  readonly checksum: string | null;
  readonly checksumAlgo: string | null;
  readonly verified: boolean;
  readonly availability: string;
}

export interface ProjectManifest {
  readonly projectId: string;
  readonly projectName: string;
  readonly status: string;
  readonly exportedAt: string;
  readonly manifestVersion: number;
  readonly assets: readonly ManifestAsset[];
  readonly replicas: readonly ManifestReplica[];
  readonly warnings: readonly string[];
}

export interface ResolveClip {
  readonly name: string;
  readonly path: string;
  readonly proxyPath: string | null;
}

export interface ResolveImportManifest {
  readonly label: string;
  readonly projectId: string;
  readonly clips: readonly ResolveClip[];
}

export interface JobSnapshot {
  readonly id: string;
  readonly state:
    | 'planned'
    | 'awaiting_review'
    | 'queued'
    | 'running'
    | 'verifying'
    | 'succeeded'
    | 'failed'
    | 'cancelled'
    | 'needs_attention'
    | 'resumable';
  readonly currentStep: string;
  readonly completedSteps: readonly string[];
  readonly totalSteps: number;
  readonly startedAt: string;
  readonly updatedAt: string;
}

export interface JobEvent {
  readonly jobId: string;
  readonly snapshot: JobSnapshot;
}

export interface MountedVolume {
  readonly path: string;
  readonly label: string;
  readonly totalBytes: number;
  readonly freeBytes: number;
  readonly filesystem: string;
}

export interface ListVolumesResult {
  readonly volumes: readonly MountedVolume[];
}

/**
 * The method catalog. The `key` is the method name; the `value`
 * param/result types enforce the contract on both sides.
 *
 * Adding a method:
 *   1. Add the entry here with its params and result interfaces.
 *   2. Add the matching pydantic models in
 *      `src/media_mate/service/protocol.py`.
 *   3. Add a corresponding test in `tests/ipc-contract.test.ts`.
 */
export interface MethodCatalog {
  'app.getStatus': { params: Record<string, never>; result: AppStatus };
  'app.getCapabilities': { params: Record<string, never>; result: GetCapabilities };
  'project.list': { params: Record<string, never>; result: ListProjectsResult };
  'project.create': { params: CreateProjectParams; result: CreateProjectResult };
  'project.get': { params: { projectId: string }; result: ProjectDetail };
  'project.update': { params: UpdateProjectParams; result: ProjectDetail };
  'project.archive': { params: ArchiveProjectParams; result: ProjectDetail };
  'source.listVolumes': { params: Record<string, never>; result: ListVolumesResult };
  'source.inspect': { params: SourceInspectParams; result: SourceInspectResult };
  'profile.save': { params: SaveProfileParams; result: OrganizationProfile };
  'profile.list': { params: Record<string, never>; result: ListProfilesResult };
  'profile.get': { params: { id: number }; result: OrganizationProfile };
  'asset.list': { params: ListAssetsParams; result: ListAssetsResult };
  'asset.get': { params: { assetId: string }; result: AssetSummary };
  'replica.verify': { params: VerifyReplicaParams; result: VerifyReplicaResult };
  'replica.list': { params: { assetId: string }; result: ListReplicasResult };
  'intake.createSession': {
    params: CreateIntakeSessionParams;
    result: IntakeSession;
  };
  'intake.addDestination': { params: AddDestinationParams; result: IntakeDestination };
  'intake.evaluate': { params: { sessionId: string }; result: SafeToFormatEval };
  'job.create': { params: CreateJobParams; result: JobDetail };
  'job.list': { params: { projectId?: string }; result: ListJobsResult };
  'job.get': { params: { id: string }; result: JobDetail };
  'job.transition': { params: JobTransitionParams; result: JobDetail };
  'job.cancel': { params: CancelJobParams; result: Record<string, never> };
  'job.recover': { params: Record<string, never>; result: string[] };
  'plan.build': { params: BuildPlanParams; result: IntakePlan };
  'receipt.export': { params: ExportReceiptParams; result: ExportReceiptResult };
  'reconcile.asset': { params: ReconcileAssetParams; result: ReconcileReport };
  'reconcile.project': { params: ReconcileProjectParams; result: ReconcileReport[] };
  'reconcile.acceptChange': { params: AcceptChangeParams; result: ReconcileReport };
  'organize.preview': { params: OrganizePreviewParams; result: OrganizePreview };
  'organize.apply': { params: OrganizeApplyParams; result: OrganizeResult };
  'clips.detect': { params: DetectClipsParams; result: LogicalClip[] };
  'clips.list': { params: DetectClipsParams; result: LogicalClip[] };
  'derivatives.list': { params: { assetId: string }; result: DerivativeSummary[] };
  'manifest.export': { params: { projectId: string }; result: ProjectManifest };
  'manifest.handoff': { params: { projectId: string }; result: string };
  'manifest.resolve': { params: { projectId: string }; result: ResolveImportManifest };
  'audit.list': { params: ListAuditParams; result: ListAuditResult };
  'audit.backfill': { params: Record<string, never>; result: number };
  'job.subscribe': { params: { jobId: string }; result: JobSnapshot };
  'job.unsubscribe': { params: { jobId: string }; result: Record<string, never> };
}

export type MethodName = keyof MethodCatalog;
export type ParamsOf<M extends MethodName> = MethodCatalog[M]['params'];
export type ResultOf<M extends MethodName> = MethodCatalog[M]['result'];

/**
 * Event subscription topics. The sidecar emits these; the renderer
 * subscribes via `job.subscribe` (the only foundation event in the
 * first cut).
 */
export interface EventCatalog {
  'job.updated': JobEvent;
  'sidecar.ready': { timestamp: string };
  'sidecar.crashed': { timestamp: string; exitCode: number | null };
}

export type EventName = keyof EventCatalog;
export type EventPayloadOf<E extends EventName> = EventCatalog[E];
