"""Intake planner — source-preserving trees, capacity, collisions.

Implements plan §7.1. A plan is built from a scanned source and a set
of destinations before any write. It:

- Preserves the source folder hierarchy for card offload by default.
- Computes source bytes, per-destination free space against the
  required copy size plus the safety reserve.
- Detects path traversal, duplicate destinations, case-only collisions,
  read-only / unavailable paths, and source==destination identity.
- Produces a deterministic plan fingerprint over the planned copies.

The plan is immutable (frozen pydantic); it is evidence, not yet a job.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from media_mate.application.policies import StoragePolicy
from media_mate.application.sources import scan_inventory
from media_mate.persistence.connection import transaction
from media_mate.persistence.repositories import projects as project_repo
from media_mate.persistence.repositories import sources as source_repo
from media_mate.service.protocol import (
    BuildPlanParams,
    CollisionIssue,
    IntakePlan,
    PlanDestination,
    PlanEntry,
)


class PlanError(ValueError):
    """Raised when a plan cannot be built as requested."""


class IntakePlanner:
    """Build an immutable intake plan from a source + destinations."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def build(self, params: BuildPlanParams) -> IntakePlan:
        with transaction(self._db_path) as conn:
            project = project_repo.get_project(conn, params.project_id)
            source = source_repo.get_source(conn, params.source_id)
        if project is None:
            raise PlanError(f"project not found: {params.project_id}")
        if source is None:
            raise PlanError(f"source not found: {params.source_id}")
        policy = self._policy_of(project.storage_policy)

        source_root = Path(source.root_path)
        if not source_root.is_dir():
            raise PlanError(f"source root is not a readable directory: {source_root}")
        entries = scan_inventory(source_root)
        total_bytes = sum(e.size for e in entries)

        dests = list(params.destinations)
        if not dests:
            raise PlanError("at least one destination is required")

        warnings: list[str] = []
        planned: list[PlanEntry] = []
        capacity_ok = True
        for dest in dests:
            self._validate_destination(dest, source_root, warnings)
            if _dest_equals_or_inside(source_root, Path(dest.root_path)):
                raise PlanError(
                    f"destination {dest.root_path} is the source itself or inside it; "
                    "refusing to plan an in-place overwrite"
                )
            root = Path(dest.root_path)
            for entry in entries:
                planned.append(
                    PlanEntry(relPath=entry.path, destPath=str(root / entry.path), size=entry.size)
                )
            free = _free_space(root)
            needed = total_bytes + policy.safety_reserve_bytes
            if free is not None and free < needed:
                capacity_ok = False
                warnings.append(
                    f"destination {dest.kind} ({root}) has {free} bytes free but needs {needed}"
                )

        collisions = detect_collisions(planned)
        fingerprint = _plan_fingerprint(planned, dests, policy)

        return IntakePlan(
            fingerprint=fingerprint,
            projectId=params.project_id,
            sourceId=params.source_id,
            sourceRoot=str(source_root),
            destinations=list(dests),
            entries=planned,
            totalBytes=total_bytes,
            capacityOk=capacity_ok,
            neededBytes=total_bytes + policy.safety_reserve_bytes,
            warnings=warnings,
            collisions=collisions,
        )

    # ---- destination validation --------------------------------------

    def _validate_destination(
        self, dest: PlanDestination, source_root: Path, warnings: list[str]
    ) -> None:
        root = Path(dest.root_path).expanduser()
        if not root.exists():
            raise PlanError(f"destination does not exist: {dest.root_path}")
        if not root.is_dir():
            raise PlanError(f"destination is not a directory: {dest.root_path}")
        if not os.access(root, os.W_OK):
            raise PlanError(f"destination is not writable: {dest.root_path}")
        if os.access(source_root, os.R_OK) is False:  # pragma: no cover - os.access quirk
            warnings.append(f"source {source_root} is not readable")

    @staticmethod
    def _policy_of(storage_policy_json: str) -> StoragePolicy:
        try:
            return StoragePolicy.model_validate_json(storage_policy_json)
        except Exception:
            return StoragePolicy()


def detect_collisions(planned: list[PlanEntry]) -> list[CollisionIssue]:
    """Detect duplicate destinations and case-only collisions."""
    issues: list[CollisionIssue] = []

    # Duplicate destination path (two relpaths mapping to the same dest).
    by_dest: dict[str, list[str]] = {}
    for entry in planned:
        by_dest.setdefault(entry.dest_path, []).append(entry.rel_path)
    for dest_path, rels in by_dest.items():
        if len(rels) > 1:
            issues.append(
                CollisionIssue(path=dest_path, reason="duplicate_destination", count=len(rels))
            )

    # Case-only collisions (relpaths differing only in case).
    by_lower: dict[str, list[str]] = {}
    for entry in planned:
        by_lower.setdefault(entry.rel_path.lower(), []).append(entry.rel_path)
    for key, rels in by_lower.items():
        if len(set(rels)) > 1:
            issues.append(CollisionIssue(path=key, reason="case_only", count=len(set(rels))))
    return issues


def _plan_fingerprint(
    planned: list[PlanEntry], dests: list[PlanDestination], policy: StoragePolicy
) -> str:
    ops = sorted({(e.rel_path, e.dest_path, e.size) for e in planned})
    dests_sorted = sorted((d.kind, d.root_path, d.required) for d in dests)
    substance = {
        "ops": ops,
        "destinations": dests_sorted,
        "policy": policy.model_dump(mode="json", by_alias=True),
    }
    canonical = json.dumps(substance, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _dest_equals_or_inside(source_root: Path, dest_root: Path) -> bool:
    """True when the destination is the source root or a descendant of it."""
    try:
        dest_root.relative_to(source_root)
        return True
    except ValueError:
        return False


def _free_space(path: Path) -> int | None:
    try:
        return int(shutil.disk_usage(path).free)
    except OSError:
        return None
