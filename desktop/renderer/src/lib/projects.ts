/**
 * Pure Projects-screen logic (testable without React/DOM).
 *
 * Derives storage-policy health per project and aggregates asset /
 * replica / derivative / receipt counts. Used by the Projects list and
 * the Project detail views.
 */
import type {
  ProjectSummary,
  StoragePolicy,
  AssetSummary,
  ReplicaSummary,
  DerivativeSummary,
} from '../../../shared/ipc-methods.js';

export type PolicyHealth = 'ok' | 'warn' | 'danger';

/**
 * Storage-policy health:
 * - danger when a backup is required but no backup root is set
 * - warn when the policy asks for multiple replicas but none verified
 * - otherwise ok
 */
export function policyHealth(project: ProjectSummary, verifiedReplicas: number): PolicyHealth {
  if (project.storagePolicy.requiredReplicas > 1 && !project.backupRoot) {
    return 'danger';
  }
  if (
    project.storagePolicy.requiredReplicas > 1 &&
    verifiedReplicas < project.storagePolicy.requiredReplicas
  ) {
    return 'warn';
  }
  return 'ok';
}

/** A project row for the Projects list, with aggregates and health. */
export interface ProjectRow {
  readonly project: ProjectSummary;
  readonly assets: number;
  readonly verifiedReplicas: number;
  readonly readyDerivatives: number;
  readonly health: PolicyHealth;
}

/** Aggregate the counts and health for one project. */
export function projectRow(
  project: ProjectSummary,
  assets: readonly AssetSummary[],
  replicas: readonly ReplicaSummary[],
  derivatives: readonly DerivativeSummary[],
): ProjectRow {
  const verifiedReplicas = replicas.filter((r) => r.verified).length;
  const readyDerivatives = derivatives.filter((d) => d.status === 'ready').length;
  return {
    project,
    assets: assets.length,
    verifiedReplicas,
    readyDerivatives,
    health: policyHealth(project, verifiedReplicas),
  };
}

/** A human label for the required-replicas policy. */
export function policyLabel(policy: StoragePolicy): string {
  const algo = policy.checksumAlgo;
  const backup = policy.backupOnDifferentVolume ? 'backup' : 'single-volume';
  return `${policy.requiredReplicas} replica(s) · ${algo} · ${backup}`;
}
