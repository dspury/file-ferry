"""Project service — CRUD, destination validation, and receipts.

Implements the plan Section 4.1 (create and configure a project) and
Package 2's project service. Every create/update persists an immutable
operation receipt (ADR-0003 §6.5) and validates the storage policy
against the default floor (ADR-0004). Destination validation covers
writability, free space against the safety reserve, and the
same-volume-backup rule.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from media_mate.application.policies import (
    StoragePolicy,
    default_policy,
    validate_policy,
)
from media_mate.application.receipts import ReceiptStore, build_receipt
from media_mate.persistence.connection import transaction
from media_mate.persistence.repositories import projects as project_repo
from media_mate.persistence.repositories.projects import ProjectRow
from media_mate.service.protocol import (
    CreateProjectParams,
    ProjectDetail,
    ProjectSummary,
    UpdateProjectParams,
)

APP_VERSION = "0.2.4"  # mirrors pyproject.toml until vNext bumps it


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ProjectValidationError(ValueError):
    """Raised when a project cannot be created/updated as requested."""


class ProjectNotFoundError(KeyError):
    """Raised when a named project does not exist."""


class ProjectService:
    """CRUD for the vNext ``projects`` entity."""

    def __init__(self, db_path: Path, app_data_dir: Path, protocol_version: int) -> None:
        self._db_path = Path(db_path)
        self._app_data_dir = Path(app_data_dir)
        self._protocol_version = protocol_version
        self._receipts = ReceiptStore(self._app_data_dir)

    # ---- create ------------------------------------------------------

    def create(self, params: CreateProjectParams) -> ProjectDetail:
        """Create a project. Validates destinations and policy, writes a receipt."""
        policy = params.storage_policy if params.storage_policy is not None else default_policy()
        validate_policy(policy, acknowledge_weaker=params.acknowledge_weaker)
        self._validate_destinations(params.working_root, params.backup_root, policy)

        project_id = str(uuid.uuid4())
        now = _now_iso()
        policy_json = policy.model_dump_json(by_alias=True)
        row = ProjectRow(
            id=project_id,
            name=params.name.strip(),
            status="active",
            working_root=params.working_root,
            backup_root=params.backup_root,
            storage_policy=policy_json,
            organization_profile_id=None,
            proxy_defaults=None,
            resolve_defaults=None,
            created_at=now,
            updated_at=now,
            archived_at=None,
        )
        receipt = build_receipt(
            operation_id=str(uuid.uuid4()),
            kind="project",
            app_version=APP_VERSION,
            protocol_version=self._protocol_version,
            policy=policy,
            planned=[{"action": "create_project", "project_id": project_id, "name": row.name}],
            actual=[{"project_id": project_id, "name": row.name}],
            final_state="created",
        )
        try:
            with transaction(self._db_path) as conn:
                if project_repo.get_project_by_name(conn, row.name) is not None:
                    raise ProjectValidationError(f"a project named {row.name!r} already exists")
                project_repo.insert_project(conn, row)
                self._receipts.write(conn, receipt)
        except ProjectValidationError:
            raise
        return self._detail_from_row(row, policy)

    # ---- read --------------------------------------------------------

    def list(self) -> list[ProjectSummary]:
        with transaction(self._db_path) as conn:
            rows = project_repo.list_projects(conn)
        return [self._summary_from_row(r) for r in rows]

    def get(self, project_id: str) -> ProjectDetail:
        with transaction(self._db_path) as conn:
            row = project_repo.get_project(conn, project_id)
        if row is None:
            raise ProjectNotFoundError(project_id)
        return self._detail_from_row(row, self._policy_of(row))

    # ---- update ------------------------------------------------------

    def update(self, params: UpdateProjectParams) -> ProjectDetail:
        with transaction(self._db_path) as conn:
            row = project_repo.get_project(conn, params.id)
            if row is None:
                raise ProjectNotFoundError(params.id)
            policy = (
                params.storage_policy if params.storage_policy is not None else self._policy_of(row)
            )
            validate_policy(policy, acknowledge_weaker=params.acknowledge_weaker)
            working = params.working_root if params.working_root is not None else row.working_root
            backup = params.backup_root if params.backup_root is not None else row.backup_root
            self._validate_destinations(working, backup, policy)

            name = params.name.strip() if params.name is not None else row.name
            existing = project_repo.get_project_by_name(conn, name)
            if existing is not None and existing.id != params.id:
                raise ProjectValidationError(f"a project named {name!r} already exists")

            updated_at = _now_iso()
            project_repo.update_project(
                conn,
                params.id,
                name=params.name.strip() if params.name is not None else None,
                working_root=params.working_root,
                backup_root=params.backup_root,
                storage_policy=(
                    policy.model_dump_json(by_alias=True)
                    if params.storage_policy is not None
                    else None
                ),
                updated_at=updated_at,
            )
            receipt = build_receipt(
                operation_id=str(uuid.uuid4()),
                kind="project",
                app_version=APP_VERSION,
                protocol_version=self._protocol_version,
                policy=policy,
                planned=[{"action": "update_project", "project_id": params.id}],
                actual=[{"project_id": params.id}],
                final_state="updated",
            )
            self._receipts.write(conn, receipt)
            updated_row = project_repo.get_project(conn, params.id)
        assert updated_row is not None
        return self._detail_from_row(updated_row, policy)

    def archive(self, project_id: str) -> ProjectDetail:
        with transaction(self._db_path) as conn:
            row = project_repo.get_project(conn, project_id)
            if row is None:
                raise ProjectNotFoundError(project_id)
            now = _now_iso()
            project_repo.update_project(
                conn, project_id, status="archived", archived_at=now, updated_at=now
            )
            receipt = build_receipt(
                operation_id=str(uuid.uuid4()),
                kind="project",
                app_version=APP_VERSION,
                protocol_version=self._protocol_version,
                policy=self._policy_of(row),
                planned=[{"action": "archive_project", "project_id": project_id}],
                actual=[{"project_id": project_id}],
                final_state="archived",
            )
            self._receipts.write(conn, receipt)
            updated_row = project_repo.get_project(conn, project_id)
        assert updated_row is not None
        return self._detail_from_row(updated_row, self._policy_of(updated_row))

    # ---- mapping / validation helpers --------------------------------

    def _summary_from_row(self, row: ProjectRow) -> ProjectSummary:
        return ProjectSummary(
            id=row.id,
            name=row.name,
            workingRoot=row.working_root,
            backupRoot=row.backup_root,
            status=row.status,
            storagePolicy=self._policy_of(row),
            createdAt=row.created_at,
            updatedAt=row.updated_at,
            archivedAt=row.archived_at,
        )

    def _detail_from_row(self, row: ProjectRow, policy: StoragePolicy) -> ProjectDetail:
        return ProjectDetail(
            id=row.id,
            name=row.name,
            workingRoot=row.working_root,
            backupRoot=row.backup_root,
            status=row.status,
            storagePolicy=policy,
            createdAt=row.created_at,
            updatedAt=row.updated_at,
            archivedAt=row.archived_at,
            organizationProfileId=row.organization_profile_id,
            proxyDefaults=json.loads(row.proxy_defaults) if row.proxy_defaults else None,
            resolveDefaults=json.loads(row.resolve_defaults) if row.resolve_defaults else None,
        )

    @staticmethod
    def _policy_of(row: ProjectRow) -> StoragePolicy:
        try:
            return StoragePolicy.model_validate_json(row.storage_policy)
        except Exception:
            return default_policy()

    def _validate_destinations(
        self, working_root: str, backup_root: str | None, policy: StoragePolicy
    ) -> None:
        working = _ensure_writable(working_root, "working root")
        _check_free_space(working, policy.safety_reserve_bytes)
        if backup_root is not None:
            backup = _ensure_writable(backup_root, "backup root")
            _check_free_space(backup, policy.safety_reserve_bytes)
            if policy.backup_on_different_volume and _same_volume(working, backup):
                raise ProjectValidationError(
                    "backup root must be on a different physical volume than the working root "
                    "(default policy; opt out only by acknowledging a weaker policy)"
                )


def _ensure_writable(path_str: str, what: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.exists():
        raise ProjectValidationError(f"{what} does not exist: {path}")
    if not path.is_dir():
        raise ProjectValidationError(f"{what} is not a directory: {path}")
    if not os.access(path, os.W_OK):
        raise ProjectValidationError(f"{what} is not writable: {path}")
    return path


def _check_free_space(path: Path, reserve: int) -> None:
    usage = shutil.disk_usage(path)
    if usage.free < reserve:
        raise ProjectValidationError(
            f"insufficient free space on {path}: {usage.free} bytes available, {reserve} reserved"
        )


def _same_volume(a: Path, b: Path) -> bool:
    """Return True when two paths live on the same filesystem/device."""
    return os.stat(a).st_dev == os.stat(b).st_dev
