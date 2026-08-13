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
