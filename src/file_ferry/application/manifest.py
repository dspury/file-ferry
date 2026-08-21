"""Project manifest + handoff export (plan §4.5, §7.4).

Produces a portable, reviewable JSON manifest describing project media,
replicas, derivatives, and warnings; a human-readable Markdown handoff;
and a clearly-labeled Resolve *import* manifest. Per plan §7.4, the
Resolve output is a manifest for import, never a claim that a Resolve
project was created.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from file_ferry.persistence.connection import transaction
from file_ferry.persistence.repositories import projects as project_repo
from file_ferry.persistence.repositories.assets import AssetRow
from file_ferry.service.protocol import (
    ManifestAsset,
    ManifestReplica,
    ProjectManifest,
    ResolveClip,
    ResolveImportManifest,
)

MANIFEST_VERSION = 1


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ManifestError(ValueError):
    """Raised when a manifest cannot be built."""


class ManifestService:
    """Build portable project manifests and handoff exports."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def export_project(self, project_id: str) -> ProjectManifest:
        """Build a portable JSON manifest for a project."""
        with transaction(self._db_path) as conn:
            project = project_repo.get_project(conn, project_id)
            if project is None:
                raise ManifestError(f"project not found: {project_id}")
            assets = [
                AssetRow.from_row(r)
                for r in conn.execute(
                    "SELECT DISTINCT a.* FROM assets a "
                    "JOIN replicas r ON r.asset_id = a.id "
                    "WHERE r.project_id = ? ORDER BY a.source_relative_path ASC",
                    (project_id,),
                ).fetchall()
            ]
            replicas = conn.execute(
                "SELECT * FROM replicas WHERE project_id = ? ORDER BY id ASC", (project_id,)
            ).fetchall()
            warnings = self._collect_warnings(conn, project_id)

        return ProjectManifest(
            projectId=project_id,
            projectName=project.name,
            status=project.status,
            exportedAt=_now_iso(),
            manifestVersion=MANIFEST_VERSION,
            assets=[
                ManifestAsset(
                    id=a.id,
                    sourceRelativePath=a.source_relative_path,
                    observedSize=a.observed_size,
                    lifecycleState=a.lifecycle_state,
                    mediaKind=a.media_kind,
                )
                for a in assets
            ],
            replicas=[
                ManifestReplica(
                    assetId=r["asset_id"],
                    path=r["path"],
                    checksum=r["checksum"],
                    checksumAlgo=r["checksum_algo"],
                    verified=bool(r["verified"]),
                    availability=r["availability"],
                )
                for r in replicas
            ],
            warnings=warnings,
        )

    def export_handoff(self, project_id: str) -> str:
        """Render a human-readable Markdown handoff report."""
        manifest = self.export_project(project_id)
        lines = [
            f"# Ferry project handoff: {manifest.project_name}",
            "",
            f"- **Project id:** `{manifest.project_id}`",
            f"- **Status:** {manifest.status}",
            f"- **Exported at:** {manifest.exported_at}",
            f"- **Manifest version:** {manifest.manifest_version}",
            f"- **Assets:** {len(manifest.assets)}",
            f"- **Replicas:** {len(manifest.replicas)}",
            "",
        ]
        if manifest.warnings:
            lines.append("## Warnings")
            lines.append("")
            for w in manifest.warnings:
                lines.append(f"- {w}")
            lines.append("")
        verified = sum(1 for r in manifest.replicas if r.verified)
        lines.append(
            f"## Verification\n\n- Verified replicas: {verified}/{len(manifest.replicas)}\n"
        )
        lines.append("## Replicas\n\n")
        for r in manifest.replicas:
            mark = "verified" if r.verified else f"{r.availability}"
            lines.append(f"- `{r.path}` ({r.checksum_algo or 'no-algo'}, {mark})")
        return "\n".join(lines) + "\n"

    def export_resolve_manifest(self, project_id: str) -> ResolveImportManifest:
        """Build a clearly-labeled manifest for Resolve import (not a project)."""
        with transaction(self._db_path) as conn:
            project = project_repo.get_project(conn, project_id)
            if project is None:
                raise ManifestError(f"project not found: {project_id}")
            rows = conn.execute(
                """
                SELECT r.path, r.asset_id FROM replicas r
                WHERE r.project_id = ? AND r.verified = 1 AND r.availability = 'present'
                ORDER BY r.path ASC
                """,
                (project_id,),
            ).fetchall()
        clips = [
            ResolveClip(name=Path(r["path"]).name, path=r["path"], proxyPath=None) for r in rows
        ]
        return ResolveImportManifest(
            label="Ferry import manifest (for DaVinci Resolve import — not a created project)",
            projectId=project_id,
            clips=clips,
        )

    # ---- helpers -----------------------------------------------------

    @staticmethod
    def _collect_warnings(conn: sqlite3.Connection, project_id: str) -> list[str]:
        warnings: list[str] = []
        missing = conn.execute(
            "SELECT COUNT(*) AS n FROM replicas WHERE project_id = ? AND availability = 'missing'",
            (project_id,),
        ).fetchone()
        if int(missing["n"]) > 0:
            warnings.append(f"{missing['n']} replica(s) missing on disk")
        return warnings
