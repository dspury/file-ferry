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
import type { JsonObject } from './ipc-schema.js';

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
  readonly proxyDefaults: JsonObject | null;
  readonly resolveDefaults: JsonObject | null;
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
  /** Non-regular findings are flagged; regular files keep the default. */
  readonly entryType?: 'file' | 'dir' | 'symlink' | 'other';
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
  /** True only when the caller supplied an explicit entry cap. */
  readonly truncated?: boolean;
  /** Exact count of scan failures; `scanErrors` is a bounded sample. */
  readonly errorCount?: number;
  readonly scanErrors?: readonly string[];
  /** Symlinks and unsupported objects — first-class findings, not hidden. */
  readonly nonFiles?: readonly SourceInventoryEntry[];
  /** Directories found, including empty ones (preserved on transfer). */
  readonly dirCount?: number;
}

/** Volume identity evidence (destination-presets spec §5.1). */
export interface DestinationIdentity {
  readonly kind: 'volume_uuid' | 'disk_uuid' | 'server_share' | 'path_only';
  readonly value: string;
  readonly confidence: 'strong' | 'medium' | 'weak';
  readonly provenance: string;
  /** When this evidence was actually observed. */
  readonly observedAt?: string | null;
  /**
   * True when the evidence was remembered from an earlier observation
   * rather than read on the latest pass. Keep showing it — "this looked
   * like your Backup drive" is useful — but never treat it as current:
   * a drive can be swapped between two observations, so not having
   * witnessed an unmount proves nothing about continuity (spec §5.1).
   */
  readonly stale?: boolean;
}

/** Destination-preset rule match conditions (spec §6.1). */
export interface PresetMatchConditions {
  readonly pathGlob?: string | null;
  readonly extensions?: readonly string[] | null;
  readonly categories?: readonly string[] | null;
  readonly sourceLabel?: string | null;
}

/** Destination-preset rule (priority by list order; first match wins). */
export interface PresetRule {
  readonly id: string;
  readonly match: PresetMatchConditions;
  readonly destination: string;
}

/**
 * Keep-together group: matched subtrees route as a unit.
 *
 * `destination` is evaluated **once**, for the group's root directory,
 * and every descendant's source-relative path is appended unchanged. Only
 * `{source_label}`, `{relative_dir}` and `{filename}` are available there
 * — the file-oriented tokens would split or relocate the subtree the user
 * marked "keep together" (spec §6.3, examples §4).
 */
export interface PresetGroup {
  readonly id: string;
  readonly match: PresetMatchConditions;
  readonly destination: string;
}

/**
 * Explicit exclusion rule, applied before routing.
 *
 * `reason` is shown in review and recorded in the receipt for every file
 * the rule leaves behind, so it is required. Excluded entries are
 * recorded as entries, never as an absence (spec §4.2, §7.3).
 */
export interface PresetExclusion {
  readonly id: string;
  readonly reason: string;
  readonly match: PresetMatchConditions;
}

/** Full content of one preset revision. */
export interface PresetContent {
  readonly name: string;
  readonly description?: string | null;
  readonly rules: readonly PresetRule[];
  readonly groups: readonly PresetGroup[];
  readonly fallbackTemplate: string;
  readonly conflictPolicy: 'keep_both' | 'skip_identical' | 'needs_review';
  readonly exclusions: readonly PresetExclusion[];
  /**
   * Content needing a human decision before this revision may be used —
   * unknown legacy template keys, legacy conflict policies with no safe
   * equivalent. A non-empty list blocks plan approval (spec §4.2).
   */
  readonly reviewRequired?: readonly string[];
}

export interface SavePresetRevisionParams {
  readonly name: string;
  readonly content: PresetContent;
}

export interface PresetRevisionSummary {
  readonly presetId: number;
  readonly revision: number;
  readonly contentHash: string;
  readonly createdAt: string;
}

export interface ListPresetRevisionsResult {
  readonly revisions: readonly PresetRevisionSummary[];
  readonly total: number;
}

export interface PresetExportResult {
  readonly presetId: number;
  readonly revision: number;
  readonly payload: string;
}

export interface PresetImportParams {
  readonly payload: string;
  readonly newName?: string | null;
}

export interface PresetRevisionDetail {
  readonly presetId: number;
  readonly revision: number;
  readonly createdAt: string;
  readonly contentHash: string;
  readonly content: PresetContent;
  readonly legacySnapshot: boolean;
  /** The legacy template this revision was converted from, verbatim. */
  readonly legacyTemplate?: JsonObject | null;
}

/** Inventory entry (server-side persisted). */
export interface InventoryEntry {
  readonly id: number;
  readonly relPath: string;
  /**
   * The kind of filesystem object. A read failure is not a type: it is
   * `scanStatus: 'error'` with the diagnostic in `error`, and
   * `entryType: 'unknown'` when the object could not be stat'd at all.
   */
  readonly entryType: 'file' | 'dir' | 'symlink' | 'other' | 'unknown';
  readonly size: number;
  readonly mtime?: number | null;
  readonly scanStatus: 'ok' | 'error';
  readonly error?: string | null;
}

export interface InventoryStatus {
  readonly id: number;
  readonly rootPath: string;
  readonly label?: string | null;
  readonly status: 'scanning' | 'complete' | 'failed';
  /** Why a scan failed; a failed scan keeps the counts it did reach. */
  readonly error?: string | null;
  readonly fileCount: number;
  readonly dirCount: number;
  readonly totalBytes: number;
  readonly errorCount: number;
  readonly excludedCount: number;
  readonly manifestHash?: string | null;
  readonly startedAt: string;
  readonly finishedAt?: string | null;
}

export interface InventoryCreateParams {
  readonly path: string;
  readonly label?: string | null;
}

export interface InventoryCreateResult {
  readonly inventoryId: number;
}

export interface InventoryStatusParams {
  readonly id: number;
}

export interface InventoryEntriesParams {
  readonly id: number;
  readonly limit?: number;
  readonly after?: number;
}

export interface InventoryEntriesPage {
  readonly entries: readonly InventoryEntry[];
  readonly total: number;
  readonly nextCursor?: number | null;
}

/** Saved destination in ``destination.list``. */
export interface DestinationSummary {
  readonly id: number;
  readonly name: string;
  readonly locationKind: 'local_folder' | 'volume_folder' | 'mounted_share_folder';
  readonly lastRootPath: string;
  readonly subfolderPath?: string | null;
  readonly identity?: DestinationIdentity | null;
  readonly defaultPresetId?: number | null;
  readonly pinnedRevision?: number | null;
  readonly conflictPolicy: 'keep_both' | 'skip_identical' | 'needs_review';
  readonly checksumAlgo: 'xxhash64' | 'sha256';
  readonly freeSpaceReserve: number;
  readonly lastBindingPath?: string | null;
  readonly lastSeenAt?: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly archivedAt?: string | null;
}

export interface ListDestinationsResult {
  readonly destinations: readonly DestinationSummary[];
}

export type DestinationAvailability =
  | 'available'
  | 'offline'
  | 'needs_confirmation'
  | 'ambiguous'
  | 'unwritable';

export interface DestinationResolution {
  readonly destinationId: number;
  readonly name: string;
  readonly status: DestinationAvailability;
  readonly reason: string;
  readonly candidatePaths: readonly string[];
  readonly bindingPath?: string | null;
}

export interface ResolveDestinationsResult {
  readonly resolutions: readonly DestinationResolution[];
}

export interface ResolveDestinationParams {
  readonly id?: number | null;
  /**
   * Re-probe the platform, or reuse the last observation. A view that
   * re-renders often should pass false and read `destination.discovery`
   * for the observation's age — slow mount metadata calls must not block
   * the UI (spec §5.2).
   */
  readonly refresh?: boolean;
}

/**
 * What storage discovery currently knows (spec §5.2).
 *
 * `stale` and `warnings` exist so a degraded probe shows as a recoverable
 * warning with manual folder selection still usable, rather than as
 * confident but wrong availability. `observedAt` of null means discovery
 * has not run — which is not the same as having observed nothing.
 */
export interface DiscoveryStatus {
  readonly volumes: readonly MountedVolume[];
  readonly observedAt?: string | null;
  readonly ageSeconds?: number | null;
  readonly stale: boolean;
  readonly warnings: readonly string[];
}

export interface ConfirmBindingParams {
  readonly destinationId: number;
  readonly path: string;
  readonly identity?: DestinationIdentity | null;
}

export interface ArchiveDestinationParams {
  readonly id: number;
}

export interface SaveDestinationParams {
  readonly name: string;
  readonly path: string;
  readonly subfolderPath?: string | null;
  readonly locationKind?: 'local_folder' | 'volume_folder' | 'mounted_share_folder' | null;
  readonly defaultPresetId?: number | null;
  /**
   * The preset revision this destination is pinned to. Omit it and the
   * current revision is pinned; a later revision of the same preset then
   * never re-routes this destination on its own (spec §4.2).
   */
  readonly pinnedRevision?: number | null;
  readonly conflictPolicy?: 'keep_both' | 'skip_identical' | 'needs_review';
  readonly checksumAlgo?: 'xxhash64' | 'sha256';
  readonly freeSpaceReserve?: number;
}

export interface TransferPlanStatus {
  readonly id: string;
  readonly destinationId?: number | null;
  readonly destinationBindingPath: string;
  readonly presetId?: number | null;
  readonly presetRevision?: number | null;
  readonly presetContentHash?: string | null;
  readonly projectId?: string | null;
  readonly fingerprint: string;
  readonly status: 'draft' | 'approved' | 'invalidated' | 'executing' | 'executed';
  readonly approvedFingerprint?: string | null;
  readonly capacityOk: boolean;
  readonly capacityUnknown: boolean;
  readonly capacityOverrideReason?: string | null;
  readonly neededBytes: number;
  readonly totalBytes: number;
  readonly totalFiles: number;
  readonly conflictCount: number;
  readonly exclusionCount: number;
  /**
   * How many of `exclusionCount` came from the preset's own exclusion
   * rules rather than a decision this reviewer made. Both are explicit;
   * §7.3 needs a receipt to be able to tell them apart.
   */
  readonly ruleExclusionCount: number;
  /**
   * Entries still needing a decision. Non-zero means approval is
   * refused (spec §7.1) — distinct from `conflictCount`, which counts
   * findings whether or not they still block.
   */
  readonly blockingCount: number;
  /**
   * Review evidence carried by the pinned preset revision. Non-empty
   * blocks approval (spec §4.2): the revision holds something Ferry
   * could not convert safely, and warning while approving anyway is the
   * silent ignore the spec forbids.
   */
  readonly presetReviewRequired: readonly string[];
  readonly freeBytes?: number | null;
  readonly freeSpaceReserve: number;
  readonly conflictPolicy: string;
  readonly checksumAlgo: string;
  readonly inventoryIds: readonly number[];
  /** The plan this one was derived from by resolving decisions. */
  readonly derivedFrom?: string | null;
  /**
   * The plan that superseded this one. Resolving a finding produces a
   * new plan and invalidates its parent, so an approved plan never
   * coexists with the revision that replaced it (spec §8).
   */
  readonly supersededBy?: string | null;
  readonly decisions: readonly PlanDecision[];
  /** The extension-map version used to classify this plan's files. */
  readonly categoryMapVersion: number;
  readonly warnings: readonly string[];
  readonly createdAt: string;
  readonly approvedAt?: string | null;
}

export interface TransferPlanEntry {
  readonly id: number;
  /**
   * Source identity is (inventory, entry) — never `relPath`, which two
   * different sources can share. Deduplicating by name drops files
   * (spec §4.3, A04).
   */
  readonly inventoryId?: number | null;
  readonly inventoryEntryId?: number | null;
  readonly sourcePath: string;
  readonly relPath: string;
  readonly entryType: string;
  readonly destRelPath: string;
  readonly matchedRule?: string | null;
  readonly size: number;
  readonly mtime?: number | null;
  readonly action: 'copy' | 'skip_identical' | 'exclude' | 'needs_review' | 'dir';
  readonly conflict?: string | null;
  readonly exclusionReason?: string | null;
  /** True only when a person chose this exclusion, never implicitly. */
  readonly excludedByUser: boolean;
  /**
   * Set when keep-both moved this copy off its natural name. Show the
   * rename in review rather than letting the receipt reveal it later.
   */
  readonly renamedFrom?: string | null;
  /**
   * The keep-together group that claimed this entry. A group's collision
   * is resolved at its root, never by renaming a member, so review has
   * to be able to show the containment (spec §6.3).
   */
  readonly groupId?: string | null;
}

export interface PlanCreateParams {
  readonly destinationId: number;
  readonly inventoryIds: readonly number[];
  readonly presetId?: number | null;
  readonly presetRevision?: number | null;
  readonly projectId?: string | null;
  readonly bindingPath?: string | null;
  readonly capacityOverrideReason?: string | null;
}

export interface PlanEntriesParams {
  readonly id: string;
  readonly limit?: number;
  readonly after?: number;
}

export interface PlanEntriesPage {
  readonly entries: readonly TransferPlanEntry[];
  readonly total: number;
  readonly nextCursor?: number | null;
}

export interface PlanApproveParams {
  readonly id: string;
  readonly fingerprint: string;
}

/**
 * One reviewed decision about a plan finding (spec §6.4).
 *
 * Keyed by (inventoryId, relPath) rather than a plan entry id: resolving
 * decisions produces a *new* plan, which reassigns entry ids, and a
 * decision that did not survive that would have to be made again every
 * round.
 */
export interface PlanDecision {
  readonly inventoryId: number;
  readonly relPath: string;
  /**
   * Exclusion removes an entry from the transfer outright.
   * `skip_identical` resolves an existing-destination conflict by asking
   * the runner to prove full content equality at execution time: if the
   * checksums disagree the item fails visibly and needs a new decision —
   * never an overwrite, never a silent skip.
   */
  readonly action?: 'exclude' | 'skip_identical';
  readonly reason?: string | null;
}

/**
 * Params for `transfer.planResolve`, which produces a **new** plan.
 *
 * Plans are immutable, so a decision never edits one. `entryIds` is what
 * a review screen has to hand; the service translates them to the stable
 * key. Decisions accumulate across rounds.
 */
export interface PlanResolveParams {
  readonly id: string;
  readonly entryIds?: readonly number[];
  readonly decisions?: readonly PlanDecision[];
  readonly reason?: string | null;
}

/**
 * A preflight run's state and findings (spec §7.1).
 *
 * Approval checks the actual source files and live storage, not just the
 * saved plan — stored rows do not move when a file is edited or a drive
 * is unplugged. `findings` is empty exactly when the run passed; each
 * entry is a sentence an operator can act on.
 */
export interface PreflightStatus {
  readonly id: number;
  readonly planId: string;
  readonly fingerprint: string;
  readonly status: 'running' | 'passed' | 'failed';
  readonly findings: readonly string[];
  readonly checkedEntries: number;
  readonly totalEntries: number;
  readonly resolvedBindingPath?: string | null;
  readonly destinationStatus?: string | null;
  readonly freeBytes?: number | null;
  readonly startedAt: string;
  readonly finishedAt?: string | null;
}

export interface PreflightStartParams {
  readonly planId: string;
}

export interface PreflightStatusParams {
  readonly id: number;
}

export interface PlanIdParams {
  readonly id: string;
}

/** MountedVolume gains an optional identity field in P3. */
export interface MountedVolume {
  readonly path: string;
  readonly label: string;
  readonly totalBytes: number;
  readonly freeBytes: number;
  readonly filesystem: string;
  readonly identity?: DestinationIdentity | null;
  /**
   * The filesystem's `st_dev`. Useless as identity — it is reassigned
   * across boots — but exactly right for "is this folder still on the
   * volume we matched?".
   */
  readonly deviceId?: number | null;
}

export interface ListVolumesResult {
  readonly volumes: readonly MountedVolume[];
}

export interface OrganizationProfile {
  readonly id: number;
  readonly name: string;
  readonly version: number;
  readonly template: JsonObject;
  readonly conflictPolicy: string;
  readonly mutationPolicy: string;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface SaveProfileParams {
  readonly name: string;
  readonly template: JsonObject;
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

export interface AdoptSourceParams {
  readonly sessionId: string;
  readonly sourceId: number;
  readonly entries: readonly SourceInventoryEntry[];
  readonly destinationRoot: string;
  readonly projectId?: string | null;
}

export interface AdoptSourceResult {
  readonly assetIds: readonly string[];
}

/**
 * Params for `transfer.start`. Takes the approved plan id **and** the
 * fingerprint it was approved under: starting a plan whose substance
 * moved is refused, and a caller never supplies paths — the plan is the
 * only source of what gets written.
 */
export interface TransferStartParams {
  readonly id: string;
  readonly fingerprint: string;
}

/**
 * The result of `transfer.start`. Returns the durable job promptly:
 * creation never waits for the copy. Starting the same approved plan
 * twice returns the same execution.
 */
export interface TransferStartResult {
  readonly job: JobDetail;
  readonly executionId: string;
}

/**
 * Params for `transfer.receipt` / `transfer.receiptExport`. Keyed by
 * plan: a plan's receipt is its latest execution's.
 */
export interface TransferReceiptParams {
  readonly planId: string;
}

/**
 * The durable receipt of a transfer, and its export state. A non-empty
 * `exportError` means the JSON export failed and is retriable; the
 * database receipt itself is the audit record and was written first.
 */
export interface TransferReceiptStatus {
  readonly executionId: string;
  readonly planId: string;
  readonly fingerprint: string;
  readonly finalState: string;
  readonly writtenAt: string;
  readonly exportedPath: string | null;
  readonly exportError: string | null;
  readonly receipt: JsonObject;
}

export interface JobDetail {
  readonly id: string;
  /** Null for a general transfer, which need not belong to a project. */
  readonly projectId: string | null;
  readonly sessionId: string | null;
  readonly command: string;
  readonly argsFingerprint: string | null;
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
  /** Omit for a general transfer, which need not belong to a project. */
  readonly projectId?: string | null;
  readonly command: string;
  readonly argsFingerprint?: string | null;
  readonly sessionId?: string | null;
  readonly totalSteps?: number;
  /**
   * The operator has already reviewed the plan, so the job should pass
   * through the plan §6.4 review gate rather than stop at it. A job
   * created without this stays `planned` and nothing will run it.
   */
  readonly reviewed?: boolean;
}

export interface JobTransitionParams {
  readonly id: string;
  readonly fromState: string;
  readonly toState: string;
}

export interface ListJobsResult {
  readonly jobs: readonly JobDetail[];
}

/** Mirrors `ListJobsParams` in `src/file_ferry/service/protocol.py`. */
export interface ListJobsParams {
  readonly projectId?: string;
}

export interface AuditEvent {
  readonly id: number;
  readonly occurredAt: string;
  readonly eventType: string;
  readonly entityType: string | null;
  readonly entityId: string | null;
  readonly data: JsonObject | null;
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

/** Checksum evidence for one verified copy; present iff `ok`. */
export interface CopyVerification {
  readonly checksumAlgo: string;
  readonly sourceChecksum: string;
  readonly destChecksum: string;
  readonly bytes: number;
  readonly mtimePreserved: boolean;
}

export interface OrganizeOutcome {
  readonly sourcePath: string;
  readonly destPath: string;
  readonly operation: string;
  readonly ok: boolean;
  readonly error: string | null;
  readonly verification?: CopyVerification | null;
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
  readonly template?: JsonObject;
  readonly mode?: 'copy' | 'move' | 'link';
}

export interface OrganizeApplyParams {
  readonly sourceRoot: string;
  readonly destRoot: string;
  readonly entries: readonly SourceInventoryEntry[];
  readonly mode?: 'copy' | 'move' | 'link';
  readonly confirmMove?: boolean;
  readonly template?: JsonObject;
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
  /**
   * Per-file progress. Steps say which phase a job is in and there are only
   * a handful of them; these say how far through the work it is, which for
   * an offload is thousands of files and terabytes.
   */
  readonly completedItems: number;
  readonly totalItems: number;
  readonly bytesCopied: number;
  readonly totalBytes: number;
}

export interface JobEvent {
  readonly jobId: string;
  readonly snapshot: JobSnapshot;
}

export interface ProfilePreviewParams {
  readonly name?: string;
  readonly template: JsonObject;
  readonly sourceRoot: string;
  readonly destRoot: string;
  readonly entries: readonly SourceInventoryEntry[];
  readonly conflictPolicy?: string;
  readonly mutationPolicy?: string;
}

export interface AppSettings {
  readonly proxyCodec: string;
  readonly proxyHeight: number;
  readonly checksumAlgo: string;
  readonly resolvePath: string | null;
  readonly ffmpegPath: string | null;
  readonly organizeTemplate: string;
  readonly organizeMode: string;
  readonly organizeOnConflict: string;
}

export interface UpdateSettingsParams {
  readonly proxyCodec?: string;
  readonly proxyHeight?: number;
  readonly checksumAlgo?: string;
  readonly resolvePath?: string | null;
  readonly ffmpegPath?: string | null;
  readonly organizeTemplate?: string;
  readonly organizeMode?: string;
  readonly organizeOnConflict?: string;
}

export interface ToolCheck {
  readonly name: string;
  readonly present: boolean;
  readonly path: string | null;
  readonly message: string | null;
}

export interface DoctorResult {
  readonly version: string;
  readonly protocolVersion: number;
  readonly tools: readonly ToolCheck[];
  readonly appDataDir: string;
  readonly dbPath: string;
}

/**
 * The method catalog. The `key` is the method name; the `value`
 * param/result types enforce the contract on both sides.
 *
 * Adding a method:
 *   1. Add the entry here with its params and result interfaces.
 *   2. Add the matching pydantic models in
 *      `src/file_ferry/service/protocol.py`.
 *   3. Add a corresponding test in `tests/ipc-contract.test.ts`.
 */
export interface MethodCatalog {
  'app.getStatus': { params: Record<string, never>; result: AppStatus };
  'app.getCapabilities': { params: Record<string, never>; result: GetCapabilities };
  'app.doctor': { params: Record<string, never>; result: DoctorResult };
  'destination.save': { params: SaveDestinationParams; result: DestinationSummary };
  'destination.list': {
    params: { includeArchived?: boolean };
    result: ListDestinationsResult;
  };
  'destination.get': { params: { id: number }; result: DestinationSummary };
  'destination.archive': { params: ArchiveDestinationParams; result: DestinationSummary };
  'destination.resolve': {
    params: ResolveDestinationParams;
    result: ResolveDestinationsResult;
  };
  'destination.discovery': { params: Record<string, never>; result: DiscoveryStatus };
  'destination.confirmBinding': {
    params: ConfirmBindingParams;
    result: DestinationSummary;
  };
  'profile.saveRevision': {
    params: SavePresetRevisionParams;
    result: PresetRevisionSummary;
  };
  'profile.listRevisions': {
    params: { presetId: number; limit?: number; after?: number };
    result: ListPresetRevisionsResult;
  };
  'profile.getRevision': {
    params: { presetId: number; revision?: number };
    result: PresetRevisionDetail;
  };
  'profile.export': {
    params: { presetId: number; revision?: number };
    result: PresetExportResult;
  };
  'profile.import': { params: PresetImportParams; result: PresetRevisionSummary };
  'inventory.create': { params: InventoryCreateParams; result: InventoryCreateResult };
  'inventory.status': { params: InventoryStatusParams; result: InventoryStatus };
  'inventory.entries': { params: InventoryEntriesParams; result: InventoryEntriesPage };
  'transfer.planCreate': { params: PlanCreateParams; result: TransferPlanStatus };
  'transfer.planGet': { params: PlanIdParams; result: TransferPlanStatus };
  'transfer.planEntries': { params: PlanEntriesParams; result: PlanEntriesPage };
  'transfer.planResolve': { params: PlanResolveParams; result: TransferPlanStatus };
  'transfer.planApprove': { params: PlanApproveParams; result: TransferPlanStatus };
  'transfer.preflightStart': { params: PreflightStartParams; result: PreflightStatus };
  'transfer.preflightStatus': { params: PreflightStatusParams; result: PreflightStatus };
  'transfer.start': { params: TransferStartParams; result: TransferStartResult };
  'transfer.receipt': { params: TransferReceiptParams; result: TransferReceiptStatus };
  'transfer.receiptExport': { params: TransferReceiptParams; result: TransferReceiptStatus };
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
  'profile.preview': { params: ProfilePreviewParams; result: OrganizePreview };
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
  'intake.adoptSource': { params: AdoptSourceParams; result: AdoptSourceResult };
  'job.create': { params: CreateJobParams; result: JobDetail };
  'job.list': { params: ListJobsParams; result: ListJobsResult };
  'job.get': { params: { id: string }; result: JobDetail };
  'job.transition': { params: JobTransitionParams; result: JobDetail };
  'job.cancel': { params: CancelJobParams; result: Record<string, never> };
  'job.dispatch': { params: { id: string }; result: Record<string, never> };
  'job.dispatchNext': { params: Record<string, never>; result: Record<string, never> };
  'job.recover': { params: Record<string, never>; result: string[] };
  'job.resume': { params: { id: string }; result: JobDetail };
  'job.retry': { params: { id: string }; result: JobDetail };
  'plan.build': { params: BuildPlanParams; result: IntakePlan };
  'receipt.export': { params: ExportReceiptParams; result: ExportReceiptResult };
  'receipt.get': { params: { operationId: string }; result: JsonObject };
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
  'settings.get': { params: Record<string, never>; result: AppSettings };
  'settings.update': { params: UpdateSettingsParams; result: AppSettings };
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
