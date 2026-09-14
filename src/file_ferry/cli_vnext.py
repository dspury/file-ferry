"""vNext CLI verbs backed by the application services (plan §9, ADR-0005).

Adds the durable, machine-readable workflow verbs the desktop sidecar
shares: ``project``, ``source``, ``intake``, ``jobs``, ``receipt``, and
``reconcile``. These call the same :class:`ApplicationService` the
sidecar uses, so the CLI and desktop are behaviorally identical — the
CLI is not a second implementation.

Legacy standalone verbs (``probe``, ``organize``, ``proxy``, ``resolve``,
``verify``, ``log``, ``run``) in ``cli.py`` are untouched.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from file_ferry.application.service import ApplicationService
from file_ferry.service.protocol import (
    ArchiveDestinationParams,
    BuildPlanParams,
    CreateProjectParams,
    ExportReceiptParams,
    InventoryCreateParams,
    InventoryEntriesParams,
    InventoryStatusParams,
    PlanApproveParams,
    PlanCreateParams,
    PlanDecision,
    PlanEntriesParams,
    PlanIdParams,
    PlanResolveParams,
    PreflightStartParams,
    PreflightStatusParams,
    ReconcileProjectParams,
    ResolveDestinationParams,
    SaveDestinationParams,
    SavePresetRevisionParams,
    SourceInspectParams,
    TransferReceiptParams,
    TransferStartParams,
)

# The ledger location is resolved by `file_ferry.paths.default_db_path` and
# threaded in from the root `--db` option; these verbs never pick their own.

console = Console()

# How long the CLI will wait for a background scan/preflight it started.
_POLL_INTERVAL_SECONDS = 0.05


def _service(db_path: Path) -> ApplicationService:
    """Build and bootstrap an ApplicationService for the given db path."""
    svc = ApplicationService(db_path=db_path, app_data_dir=db_path.parent)
    svc.bootstrap()
    return svc


def _emit_json(payload: Any) -> None:
    console.print_json(json.dumps(payload, default=str))


@click.group("project", help="Manage projects (vNext application services).")
def project_group() -> None:
    """Project management backed by ApplicationService."""


@project_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def project_list(ctx: click.Context, as_json: bool) -> None:
    """List projects."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        projects = svc.list_projects()
    finally:
        svc.close()
    if as_json:
        console.print_json(json.dumps([p.model_dump(by_alias=True) for p in projects]))
        return
    table = Table(title="Projects")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Working root")
    table.add_column("Status")
    for p in projects:
        table.add_row(p.id, p.name, p.working_root, p.status)
    console.print(table)


@project_group.command("create")
@click.argument("name")
@click.option("--working", required=True, help="Working root directory.")
@click.option("--backup", default=None, help="Backup root directory (optional).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def project_create(
    ctx: click.Context, name: str, working: str, backup: str | None, as_json: bool
) -> None:
    """Create a project."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        pid = svc.create_project(
            CreateProjectParams(name=name, workingRoot=working, backupRoot=backup)
        )
    finally:
        svc.close()
    if as_json:
        console.print_json(json.dumps({"projectId": pid}))
    else:
        console.print(f"created project {pid}")


@project_group.command("get")
@click.argument("project_id")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def project_get(ctx: click.Context, project_id: str, as_json: bool) -> None:
    """Show one project."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        detail = svc.get_project(project_id)
    finally:
        svc.close()
    if as_json:
        console.print_json(detail.model_dump_json(by_alias=True))
    else:
        console.print(f"{detail.name} ({detail.id}) · {detail.status}")
        console.print(f"  working: {detail.working_root}")
        console.print(f"  backup:  {detail.backup_root or '—'}")


@click.group("source", help="Source inspection (vNext application services).")
def source_group() -> None:
    """Source management."""


@source_group.command("inspect")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--kind", type=click.Choice(["card", "existing_media"]), default="card")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def source_inspect(ctx: click.Context, path: Path, kind: str, as_json: bool) -> None:
    """Inspect a source read-only."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        result = svc.source_inspect(
            SourceInspectParams(path=str(path), kind=kind)  # type: ignore[arg-type]
        )
    finally:
        svc.close()
    if as_json:
        console.print_json(result.model_dump_json(by_alias=True))
    else:
        console.print(
            f"source {result.source_id}: {result.file_count} files, "
            f"{result.total_bytes} bytes (kind={result.kind})"
        )


@source_group.command("list-volumes")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def source_list_volumes(ctx: click.Context, as_json: bool) -> None:
    """List mounted volumes."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        volumes = svc.list_volumes()
    finally:
        svc.close()
    if as_json:
        console.print_json(json.dumps([v.model_dump(by_alias=True) for v in volumes]))
    else:
        for v in volumes:
            console.print(f"{v.path} · {v.filesystem} · {v.free_bytes} free")


@click.group("intake", help="Intake planning (vNext application services).")
def intake_group() -> None:
    """Intake planning."""


@intake_group.command("plan")
@click.argument("project_id")
@click.argument("source_id", type=int)
@click.option("--working", required=True, help="Working destination root.")
@click.option("--backup", default=None, help="Backup destination root (optional).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def intake_plan(
    ctx: click.Context,
    project_id: str,
    source_id: int,
    working: str,
    backup: str | None,
    as_json: bool,
) -> None:
    """Build a reviewable intake plan (no writes)."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    destinations = [{"kind": "working", "rootPath": working}]
    if backup:
        destinations.append({"kind": "backup", "rootPath": backup})
    try:
        plan = svc.plan_build(
            BuildPlanParams(projectId=project_id, sourceId=source_id, destinations=destinations)  # type: ignore[arg-type]
        )
    finally:
        svc.close()
    if as_json:
        console.print_json(plan.model_dump_json(by_alias=True))
    else:
        console.print(
            f"plan {plan.fingerprint}: {len(plan.entries)} files, "
            f"{plan.total_bytes} bytes · capacity_ok={plan.capacity_ok}"
        )
        for c in plan.collisions:
            console.print(f"  collision: {c.path} ({c.reason})")


@click.group("jobs", help="Durable job management (vNext application services).")
def jobs_group() -> None:
    """Durable jobs."""


@jobs_group.command("list")
@click.option("--project", "project_id", default=None, help="Filter by project id.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def jobs_list(ctx: click.Context, project_id: str | None, as_json: bool) -> None:
    """List durable jobs."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        jobs = svc.job_list(project_id)
    finally:
        svc.close()
    if as_json:
        console.print_json(json.dumps([j.model_dump(by_alias=True) for j in jobs]))
    else:
        table = Table(title="Jobs")
        table.add_column("ID")
        table.add_column("Command")
        table.add_column("State")
        table.add_column("Project")
        for j in jobs:
            table.add_row(j.id, j.command, j.state, j.project_id)
        console.print(table)


@jobs_group.command("resume")
@click.argument("job_id")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def jobs_resume(ctx: click.Context, job_id: str, as_json: bool) -> None:
    """Resume an attention job at a safe boundary."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        job = svc.job_resume(job_id)
    finally:
        svc.close()
    if as_json:
        console.print_json(job.model_dump_json(by_alias=True))
    else:
        console.print(f"job {job.id} -> {job.state}")


@jobs_group.command("retry")
@click.argument("job_id")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def jobs_retry(ctx: click.Context, job_id: str, as_json: bool) -> None:
    """Retry a failed job with a fresh attempt."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        job = svc.job_retry(job_id)
    finally:
        svc.close()
    if as_json:
        console.print_json(job.model_dump_json(by_alias=True))
    else:
        console.print(f"job {job.id} -> {job.state}")


@click.group("receipt", help="Receipt export (vNext application services).")
def receipt_group() -> None:
    """Receipts."""


@receipt_group.command("export")
@click.argument("operation_id")
@click.option("--format", "fmt", type=click.Choice(["markdown", "html"]), default="markdown")
@click.pass_context
def receipt_export(ctx: click.Context, operation_id: str, fmt: str) -> None:
    """Export a receipt as markdown or html."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        result = svc.receipt_export(ExportReceiptParams(operationId=operation_id, format=fmt))  # type: ignore[arg-type]
    finally:
        svc.close()
    console.print(result.content)


@click.group("reconcile", help="Project reconciliation (vNext application services).")
def reconcile_group() -> None:
    """Reconciliation."""


@reconcile_group.command("project")
@click.argument("project_id")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def reconcile_project(ctx: click.Context, project_id: str, as_json: bool) -> None:
    """Reconcile a project's replicas against the filesystem."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        reports = svc.reconcile_project(ReconcileProjectParams(projectId=project_id))
    finally:
        svc.close()
    if as_json:
        console.print_json(json.dumps([r.model_dump(by_alias=True) for r in reports]))
    else:
        total = 0
        missing = 0
        for r in reports:
            for e in r.entries:
                total += 1
                if e.availability == "missing":
                    missing += 1
        console.print(f"{len(reports)} assets, {total} replicas, {missing} missing")


@receipt_group.command("get")
@click.argument("operation_id")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def receipt_get(ctx: click.Context, operation_id: str, as_json: bool) -> None:
    """Read a stored operation receipt."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        receipt = svc.receipt_get(operation_id)
    finally:
        svc.close()
    if as_json:
        _emit_json(receipt)
    else:
        console.print(f"receipt {operation_id}: {receipt.get('status', '?')}")


# ---- destinations (spec §4.1 / §5) ---------------------------------------


@click.group("destination", help="Saved destinations (vNext application services).")
def destination_group() -> None:
    """Saved destinations and their binding resolver."""


@destination_group.command("save")
@click.option("--name", required=True, help="Destination name.")
@click.option("--path", "path_", required=True, help="Destination root path.")
@click.option("--subfolder", "subfolder_path", default=None, help="Subfolder under the root.")
@click.option(
    "--kind",
    "location_kind",
    type=click.Choice(["local_folder", "volume_folder", "mounted_share_folder"]),
    default=None,
)
@click.option("--preset-id", "default_preset_id", type=int, default=None)
@click.option("--pinned-revision", "pinned_revision", type=int, default=None)
@click.option(
    "--conflict-policy",
    type=click.Choice(["keep_both", "skip_identical", "needs_review"]),
    default="keep_both",
)
@click.option("--checksum-algo", type=click.Choice(["xxhash64", "sha256"]), default="xxhash64")
@click.option("--free-space-reserve", type=int, default=0)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def destination_save(
    ctx: click.Context,
    name: str,
    path_: str,
    subfolder_path: str | None,
    location_kind: str | None,
    default_preset_id: int | None,
    pinned_revision: int | None,
    conflict_policy: str,
    checksum_algo: str,
    free_space_reserve: int,
    as_json: bool,
) -> None:
    """Save (or re-save) a destination."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        dest = svc.destination_save(
            SaveDestinationParams(
                name=name,
                path=path_,
                subfolderPath=subfolder_path,
                locationKind=location_kind,  # type: ignore[arg-type]
                defaultPresetId=default_preset_id,
                pinnedRevision=pinned_revision,
                conflictPolicy=conflict_policy,  # type: ignore[arg-type]
                checksumAlgo=checksum_algo,  # type: ignore[arg-type]
                freeSpaceReserve=free_space_reserve,
            )
        )
    finally:
        svc.close()
    if as_json:
        _emit_json(dest.model_dump(by_alias=True))
    else:
        console.print(f"saved destination {dest.id}: {dest.name} -> {dest.last_root_path}")


@destination_group.command("list")
@click.option("--include-archived", is_flag=True, help="Include archived destinations.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def destination_list(ctx: click.Context, include_archived: bool, as_json: bool) -> None:
    """List saved destinations."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        result = svc.destination_list(include_archived=include_archived)
    finally:
        svc.close()
    if as_json:
        _emit_json([d.model_dump(by_alias=True) for d in result.destinations])
        return
    table = Table(title="Destinations")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Root")
    table.add_column("Kind")
    for d in result.destinations:
        table.add_row(str(d.id), d.name, d.last_root_path, d.location_kind)
    console.print(table)


@destination_group.command("get")
@click.argument("destination_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def destination_get(ctx: click.Context, destination_id: int, as_json: bool) -> None:
    """Show one destination."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        dest = svc.destination_get(destination_id)
    finally:
        svc.close()
    if as_json:
        _emit_json(dest.model_dump(by_alias=True))
    else:
        console.print(f"{dest.name} ({dest.id}) · {dest.location_kind}")
        console.print(f"  root: {dest.last_root_path}")
        console.print(f"  preset: {dest.default_preset_id} @ {dest.pinned_revision}")


@destination_group.command("archive")
@click.argument("destination_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def destination_archive(ctx: click.Context, destination_id: int, as_json: bool) -> None:
    """Archive a destination (its unexecuted plans are invalidated)."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        dest = svc.destination_archive(ArchiveDestinationParams(id=destination_id))
    finally:
        svc.close()
    if as_json:
        _emit_json(dest.model_dump(by_alias=True))
    else:
        console.print(f"archived destination {dest.id}")


@destination_group.command("resolve")
@click.option("--id", "destination_id", type=int, default=None, help="Resolve one destination.")
@click.option(
    "--refresh/--no-refresh",
    default=True,
    help="Re-probe mounts, or reuse the last observation.",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def destination_resolve(
    ctx: click.Context, destination_id: int | None, refresh: bool, as_json: bool
) -> None:
    """Resolve saved destinations against what is actually mounted."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        result = svc.destination_resolve(
            ResolveDestinationParams(id=destination_id, refresh=refresh)
        )
    finally:
        svc.close()
    if as_json:
        _emit_json([r.model_dump(by_alias=True) for r in result.resolutions])
        return
    table = Table(title="Destination resolution")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Binding")
    for r in result.resolutions:
        table.add_row(str(r.destination_id), r.name, r.status, r.binding_path or "—")
    console.print(table)


# ---- preset revisions (spec §4.2) ----------------------------------------


@click.group("preset", help="Immutable preset revisions (vNext application services).")
def preset_group() -> None:
    """Preset revisions."""


@preset_group.command("save")
@click.option("--name", required=True, help="Preset name (created if new).")
@click.option(
    "--fallback-template",
    default=None,
    help="Fallback destination template (required unless --content-json is given).",
)
@click.option("--description", default=None)
@click.option(
    "--conflict-policy",
    type=click.Choice(["keep_both", "skip_identical", "needs_review"]),
    default="keep_both",
)
@click.option("--content-json", default=None, help="Full PresetContent as a JSON object.")
@click.option("--rules-json", default=None, help="Preset rules as a JSON array.")
@click.option("--groups-json", default=None, help="Preset groups as a JSON array.")
@click.option("--exclusions-json", default=None, help="Preset exclusions as a JSON array.")
@click.option("--review-required", multiple=True, help="A known review-required item (repeatable).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def preset_save(
    ctx: click.Context,
    name: str,
    fallback_template: str | None,
    description: str | None,
    conflict_policy: str,
    content_json: str | None,
    rules_json: str | None,
    groups_json: str | None,
    exclusions_json: str | None,
    review_required: tuple[str, ...],
    as_json: bool,
) -> None:
    """Append a new immutable revision to a preset."""
    if content_json is not None:
        content = json.loads(content_json)
    else:
        if fallback_template is None:
            raise click.UsageError("--fallback-template is required unless --content-json is given")
        content = {
            "name": name,
            "description": description,
            "fallbackTemplate": fallback_template,
            "conflictPolicy": conflict_policy,
            "rules": json.loads(rules_json) if rules_json else [],
            "groups": json.loads(groups_json) if groups_json else [],
            "exclusions": json.loads(exclusions_json) if exclusions_json else [],
            "reviewRequired": list(review_required),
        }
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        revision = svc.profile_save_revision(SavePresetRevisionParams(name=name, content=content))
    finally:
        svc.close()
    if as_json:
        _emit_json(revision.model_dump(by_alias=True))
    else:
        console.print(
            f"saved preset {revision.preset_id} revision {revision.revision} "
            f"({revision.content_hash[:12]})"
        )


@preset_group.command("list")
@click.option("--preset-id", type=int, required=True, help="Preset id to list revisions for.")
@click.option("--limit", type=int, default=50)
@click.option("--after", "after_id", type=int, default=0)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def preset_list(
    ctx: click.Context, preset_id: int, limit: int, after_id: int, as_json: bool
) -> None:
    """List a preset's revisions (newest first)."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        result = svc.profile_list_revisions(preset_id, limit=limit, after_id=after_id)
    finally:
        svc.close()
    if as_json:
        _emit_json(result.model_dump(by_alias=True))
        return
    table = Table(title=f"Preset {preset_id} revisions")
    table.add_column("Revision")
    table.add_column("Hash")
    table.add_column("Created")
    for r in result.revisions:
        table.add_row(str(r.revision), r.content_hash[:12], r.created_at)
    console.print(table)


@preset_group.command("get")
@click.option("--preset-id", type=int, required=True)
@click.option("--revision", type=int, default=None, help="Defaults to the latest revision.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def preset_get(ctx: click.Context, preset_id: int, revision: int | None, as_json: bool) -> None:
    """Show one preset revision, including its content."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        detail = svc.profile_get_revision(preset_id, revision)
    finally:
        svc.close()
    if as_json:
        _emit_json(detail.model_dump(by_alias=True))
    else:
        console.print(
            f"preset {detail.preset_id} revision {detail.revision} ({detail.content_hash[:12]})"
        )
        console.print(f"  fallback: {detail.content.fallback_template}")


@preset_group.command("export")
@click.option("--preset-id", type=int, required=True)
@click.option("--revision", type=int, default=None)
@click.pass_context
def preset_export(ctx: click.Context, preset_id: int, revision: int | None) -> None:
    """Export a preset revision as a portable payload."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        result = svc.profile_export(preset_id, revision)
    finally:
        svc.close()
    console.print(result.payload)


# ---- inventories (spec §4.3) ---------------------------------------------


@click.group("inventory", help="Source inventories (vNext application services).")
def inventory_group() -> None:
    """Source inventories."""


def _await_inventory(svc: ApplicationService, inventory_id: int, timeout: float) -> Any:
    """Poll an inventory scan until it stops scanning."""
    deadline = time.monotonic() + timeout
    while True:
        status = svc.inventory_status(InventoryStatusParams(id=inventory_id))
        if status.status != "scanning":
            return status
        if time.monotonic() > deadline:
            raise click.ClickException(
                f"inventory {inventory_id} still scanning after {timeout:g}s"
            )
        time.sleep(_POLL_INTERVAL_SECONDS)


@inventory_group.command("create")
@click.option("--path", "path_", required=True, help="Root to scan.")
@click.option("--label", default=None, help="Human label (defaults to the folder name).")
@click.option(
    "--wait/--no-wait",
    default=True,
    help="Wait for the scan to finish (default) or return immediately.",
)
@click.option("--timeout", type=float, default=3600.0, help="Seconds to wait when --wait.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def inventory_create(
    ctx: click.Context,
    path_: str,
    label: str | None,
    wait: bool,
    timeout: float,
    as_json: bool,
) -> None:
    """Create (and, by default, complete) a source inventory."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        created = svc.inventory_create(InventoryCreateParams(path=path_, label=label))
        status = _await_inventory(svc, created.inventory_id, timeout) if wait else None
    finally:
        svc.close()
    if as_json:
        if status is not None:
            _emit_json(status.model_dump(by_alias=True))
        else:
            _emit_json(created.model_dump(by_alias=True))
        return
    if status is not None:
        console.print(
            f"inventory {status.id}: {status.status}, {status.file_count} files, "
            f"{status.total_bytes} bytes"
        )
    else:
        console.print(f"inventory {created.inventory_id} scanning")


@inventory_group.command("status")
@click.argument("inventory_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def inventory_status(ctx: click.Context, inventory_id: int, as_json: bool) -> None:
    """Inspect one inventory."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        status = svc.inventory_status(InventoryStatusParams(id=inventory_id))
    finally:
        svc.close()
    if as_json:
        _emit_json(status.model_dump(by_alias=True))
    else:
        console.print(
            f"inventory {status.id}: {status.status}, {status.file_count} files, "
            f"{status.total_bytes} bytes"
        )


@inventory_group.command("entries")
@click.argument("inventory_id", type=int)
@click.option("--limit", type=int, default=200)
@click.option("--after", type=int, default=0)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def inventory_entries(
    ctx: click.Context, inventory_id: int, limit: int, after: int, as_json: bool
) -> None:
    """List inventory entries (paginated)."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        page = svc.inventory_entries(
            InventoryEntriesParams(id=inventory_id, limit=limit, after=after)
        )
    finally:
        svc.close()
    if as_json:
        _emit_json(page.model_dump(by_alias=True))
        return
    table = Table(title=f"Inventory {inventory_id} entries")
    table.add_column("ID", justify="right")
    table.add_column("Path")
    table.add_column("Type")
    table.add_column("Size", justify="right")
    for e in page.entries:
        table.add_row(str(e.id), e.rel_path, e.entry_type, str(e.size))
    console.print(table)


# ---- transfer plans (spec §4.3, §7.1) ------------------------------------


@click.group("plan", help="Transfer plans (vNext application services).")
def plan_group() -> None:
    """Transfer plans."""


@plan_group.command("create")
@click.option("--destination-id", type=int, required=True)
@click.option(
    "--inventory",
    "inventory_ids",
    type=int,
    multiple=True,
    required=True,
    help="Inventory id to include (repeatable).",
)
@click.option("--preset-id", type=int, default=None)
@click.option("--preset-revision", type=int, default=None)
@click.option("--project-id", default=None)
@click.option("--binding-path", default=None)
@click.option("--capacity-override-reason", default=None)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def plan_create(
    ctx: click.Context,
    destination_id: int,
    inventory_ids: tuple[int, ...],
    preset_id: int | None,
    preset_revision: int | None,
    project_id: str | None,
    binding_path: str | None,
    capacity_override_reason: str | None,
    as_json: bool,
) -> None:
    """Create a transfer plan (no writes)."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        plan = svc.transfer_plan_create(
            PlanCreateParams(
                destinationId=destination_id,
                inventoryIds=list(inventory_ids),
                presetId=preset_id,
                presetRevision=preset_revision,
                projectId=project_id,
                bindingPath=binding_path,
                capacityOverrideReason=capacity_override_reason,
            )
        )
    finally:
        svc.close()
    if as_json:
        _emit_json(plan.model_dump(by_alias=True))
    else:
        console.print(
            f"plan {plan.id} ({plan.status}) · {plan.total_files} files, "
            f"{plan.total_bytes} bytes · fingerprint {plan.fingerprint[:12]}"
        )


@plan_group.command("get")
@click.argument("plan_id")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def plan_get(ctx: click.Context, plan_id: str, as_json: bool) -> None:
    """Inspect one plan."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        plan = svc.transfer_plan_get(PlanIdParams(id=plan_id))
    finally:
        svc.close()
    if as_json:
        _emit_json(plan.model_dump(by_alias=True))
    else:
        console.print(
            f"plan {plan.id} ({plan.status}) · {plan.total_files} files, "
            f"{plan.conflict_count} conflicts, {plan.blocking_count} blocking"
        )


@plan_group.command("entries")
@click.argument("plan_id")
@click.option("--limit", type=int, default=200)
@click.option("--after", type=int, default=0)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def plan_entries(ctx: click.Context, plan_id: str, limit: int, after: int, as_json: bool) -> None:
    """List plan entries (paginated)."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        page = svc.transfer_plan_entries(PlanEntriesParams(id=plan_id, limit=limit, after=after))
    finally:
        svc.close()
    if as_json:
        _emit_json(page.model_dump(by_alias=True))
        return
    table = Table(title=f"Plan {plan_id} entries")
    table.add_column("ID", justify="right")
    table.add_column("Rel path")
    table.add_column("Dest rel path")
    table.add_column("Action")
    for e in page.entries:
        table.add_row(str(e.id), e.rel_path, e.dest_rel_path, e.action)
    console.print(table)


def _decision(value: str, action: str) -> PlanDecision:
    inventory, _, rel_path = value.partition(":")
    if not inventory or not rel_path:
        raise click.BadParameter("expected INVENTORY_ID:RELPATH", param_hint=value)
    return PlanDecision(inventoryId=int(inventory), relPath=rel_path, action=action)  # type: ignore[arg-type]


@plan_group.command("resolve")
@click.argument("plan_id")
@click.option("--exclude", multiple=True, help="INVENTORY_ID:RELPATH to exclude (repeatable).")
@click.option(
    "--skip-identical",
    multiple=True,
    help="INVENTORY_ID:RELPATH to resolve as skip-identical (repeatable).",
)
@click.option("--entry-id", "entry_ids", type=int, multiple=True, help="Entry id to resolve.")
@click.option("--reason", default=None)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def plan_resolve(
    ctx: click.Context,
    plan_id: str,
    exclude: tuple[str, ...],
    skip_identical: tuple[str, ...],
    entry_ids: tuple[int, ...],
    reason: str | None,
    as_json: bool,
) -> None:
    """Apply reviewed decisions, producing the next plan revision."""
    decisions = [_decision(v, "exclude") for v in exclude]
    decisions += [_decision(v, "skip_identical") for v in skip_identical]
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        plan = svc.transfer_plan_resolve(
            PlanResolveParams(
                id=plan_id,
                entryIds=list(entry_ids),
                decisions=decisions,
                reason=reason,
            )
        )
    finally:
        svc.close()
    if as_json:
        _emit_json(plan.model_dump(by_alias=True))
    else:
        console.print(
            f"plan {plan.id} ({plan.status}) · {plan.total_files} files · "
            f"fingerprint {plan.fingerprint[:12]}"
        )


@plan_group.command("approve")
@click.argument("plan_id")
@click.option("--fingerprint", required=True, help="The fingerprint to approve.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def plan_approve(ctx: click.Context, plan_id: str, fingerprint: str, as_json: bool) -> None:
    """Approve a plan (requires a current passing preflight)."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        plan = svc.transfer_plan_approve(PlanApproveParams(id=plan_id, fingerprint=fingerprint))
    finally:
        svc.close()
    if as_json:
        _emit_json(plan.model_dump(by_alias=True))
    else:
        console.print(f"plan {plan.id} -> {plan.status}")


# ---- preflight (spec §7.1) -----------------------------------------------


@click.group("preflight", help="Plan preflight (vNext application services).")
def preflight_group() -> None:
    """Preflight a plan against the live filesystem."""


def _await_preflight(svc: ApplicationService, preflight_id: int, timeout: float) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        status = svc.transfer_preflight_status(PreflightStatusParams(id=preflight_id))
        if status.status != "running":
            return status
        if time.monotonic() > deadline:
            raise click.ClickException(f"preflight {preflight_id} still running after {timeout:g}s")
        time.sleep(_POLL_INTERVAL_SECONDS)


@preflight_group.command("run")
@click.argument("plan_id")
@click.option("--timeout", type=float, default=3600.0, help="Seconds to wait.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def preflight_run(ctx: click.Context, plan_id: str, timeout: float, as_json: bool) -> None:
    """Run a preflight to completion and report its findings."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        started = svc.transfer_preflight_start(PreflightStartParams(planId=plan_id))
        status = _await_preflight(svc, started.id, timeout)
    finally:
        svc.close()
    if as_json:
        _emit_json(status.model_dump(by_alias=True))
    else:
        console.print(f"preflight {status.id}: {status.status}")
        for finding in status.findings:
            console.print(f"  {finding}")
    if status.status != "passed":
        ctx.exit(1)


@preflight_group.command("status")
@click.argument("preflight_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def preflight_status(ctx: click.Context, preflight_id: int, as_json: bool) -> None:
    """Inspect one preflight run."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        status = svc.transfer_preflight_status(PreflightStatusParams(id=preflight_id))
    finally:
        svc.close()
    if as_json:
        _emit_json(status.model_dump(by_alias=True))
    else:
        console.print(f"preflight {status.id}: {status.status}")


# ---- transfer execution (spec §7.2/§7.3) ---------------------------------


@click.group("transfer", help="Verified transfer execution (vNext application services).")
def transfer_group() -> None:
    """Run approved plans and read their receipts."""


@transfer_group.command("start")
@click.argument("plan_id")
@click.option("--fingerprint", required=True, help="The approved fingerprint.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def transfer_start(ctx: click.Context, plan_id: str, fingerprint: str, as_json: bool) -> None:
    """Start an approved plan and run it to completion.

    The background dispatcher is parked first so the copy runs
    synchronously and the command returns only when the job has finished.
    """
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        svc.dispatcher().stop()
        started = svc.transfer_start(TransferStartParams(id=plan_id, fingerprint=fingerprint))
        job = svc.job_dispatch(started.job.id)
    finally:
        svc.close()
    if as_json:
        _emit_json(
            {
                "executionId": started.execution_id,
                "jobId": job.id,
                "state": job.state,
            }
        )
    else:
        console.print(f"transfer {started.execution_id}: {job.state} (job {job.id})")
    if job.state != "succeeded":
        ctx.exit(1)


@transfer_group.command("receipt")
@click.argument("plan_id")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def transfer_receipt(ctx: click.Context, plan_id: str, as_json: bool) -> None:
    """Read a plan's latest transfer receipt."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        receipt = svc.transfer_receipt(TransferReceiptParams(planId=plan_id))
    finally:
        svc.close()
    if as_json:
        _emit_json(receipt.model_dump(by_alias=True))
    else:
        actual = receipt.receipt.get("actual", {})
        console.print(
            f"receipt {receipt.execution_id}: {receipt.final_state}, "
            f"committed={actual.get('committed')} failed={actual.get('failed')}"
        )


@transfer_group.command("receipt-export")
@click.argument("plan_id")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def transfer_receipt_export(ctx: click.Context, plan_id: str, as_json: bool) -> None:
    """Re-attempt the JSON export of a receipt."""
    db: Path = ctx.obj["db_path"]
    svc = _service(db)
    try:
        receipt = svc.transfer_receipt_export(TransferReceiptParams(planId=plan_id))
    finally:
        svc.close()
    if as_json:
        _emit_json(receipt.model_dump(by_alias=True))
    else:
        console.print(f"exported: {receipt.exported_path or receipt.export_error}")


ALL_VNEXT_GROUPS = [
    project_group,
    source_group,
    intake_group,
    jobs_group,
    receipt_group,
    reconcile_group,
    destination_group,
    preset_group,
    inventory_group,
    plan_group,
    preflight_group,
    transfer_group,
]
