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
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from file_ferry.application.service import ApplicationService
from file_ferry.service.protocol import (
    BuildPlanParams,
    CreateProjectParams,
    ExportReceiptParams,
    ReconcileProjectParams,
    SourceInspectParams,
)

# The ledger location is resolved by `file_ferry.paths.default_db_path` and
# threaded in from the root `--db` option; these verbs never pick their own.

console = Console()


def _service(db_path: Path) -> ApplicationService:
    """Build and bootstrap an ApplicationService for the given db path."""
    svc = ApplicationService(db_path=db_path, app_data_dir=db_path.parent)
    svc.bootstrap()
    return svc


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


ALL_VNEXT_GROUPS = [
    project_group,
    source_group,
    intake_group,
    jobs_group,
    receipt_group,
    reconcile_group,
]
