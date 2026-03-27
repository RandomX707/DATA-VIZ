from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from agents import chart_strategist, qa_reviewer, requirements_parser
from config import config
from models.schemas import CatalogueEntry, DashboardPlan
from tools.catalogue import CatalogueManager
from tools.column_sampler import ColumnSampler
from tools.notifier import Notifier
from tools.superset_api import SupersetClient, build_position_json

app = typer.Typer(add_completion=False)
console = Console()

RUNS_DIR = Path(__file__).parent / "runs"
PREVIEWS_DIR = Path(__file__).parent / "previews"
RUNS_DIR.mkdir(exist_ok=True)
PREVIEWS_DIR.mkdir(exist_ok=True)


# ── State helpers ────────────────────────────────────────────────────────────

def _state_path(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}.json"


def _load_state(run_id: str) -> dict:
    p = _state_path(run_id)
    if p.exists():
        return json.loads(p.read_text())
    return {"run_id": run_id, "completed_steps": []}


def _save_state(run_id: str, state: dict) -> None:
    _state_path(run_id).write_text(json.dumps(state, indent=2, default=str))


def _step_done(state: dict, step: str) -> bool:
    return step in state.get("completed_steps", [])


def _mark_done(state: dict, step: str) -> None:
    state.setdefault("completed_steps", []).append(step)


# ── Preview builder ──────────────────────────────────────────────────────────

def _build_preview(
    run_id: str,
    dashboard_plan: DashboardPlan,
    dataset_name: str,
    flagged: list[str],
) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# Dashboard Plan: {dashboard_plan.dashboard_title}",
        f"Generated: {ts}",
        f"Dataset: {dataset_name}",
        "",
        "## Charts",
        "",
        "| # | Title | Type | Columns | Width |",
        "|---|-------|------|---------|-------|",
    ]
    for i, chart in enumerate(dashboard_plan.charts, 1):
        cols = list(chart.groupby)
        for m in chart.metrics:
            col = (m.get("column") or {}).get("column_name")
            if col and col not in cols:
                cols.append(col)
        if chart.time_column and chart.time_column not in cols:
            cols.append(chart.time_column)
        lines.append(
            f"| {i} | {chart.title} | {chart.viz_type} | {', '.join(cols)} | {chart.width} |"
        )

    lines += [
        "",
        "## Filter Bar",
        "",
        "| Column | Type | Label |",
        "|--------|------|-------|",
    ]
    for f in dashboard_plan.filters:
        lines.append(f"| {f.column_name} | {f.filter_type} | {f.label} |")

    if flagged:
        lines += ["", "## Flagged Requirements", ""]
        for item in flagged:
            lines.append(f"- {item}")

    # Layout section
    lines += ["", "## Layout", ""]
    rows: list[list[tuple[str, int]]] = []
    current: list[tuple[str, int]] = []
    remaining = 12
    for chart in dashboard_plan.charts:
        w = chart.width
        if w <= remaining:
            current.append((chart.title, w))
            remaining -= w
        else:
            if current:
                rows.append(current)
            current = [(chart.title, w)]
            remaining = 12 - w
    if current:
        rows.append(current)

    for i, row in enumerate(rows, 1):
        items = " ".join(f"[{title} ({w})]" for title, w in row)
        lines.append(f"Row {i}: {items}")

    preview_path = PREVIEWS_DIR / f"{run_id}.md"
    preview_path.write_text("\n".join(lines))
    return preview_path


# ── Confirmation table ───────────────────────────────────────────────────────

def _print_plan(dashboard_plan: DashboardPlan) -> None:
    table = Table(title=f"Dashboard Plan: {dashboard_plan.dashboard_title}", show_lines=True)
    table.add_column("Title", style="cyan")
    table.add_column("Viz type", style="magenta")
    table.add_column("Width", justify="right")
    table.add_column("Columns used")

    for chart in dashboard_plan.charts:
        cols: list[str] = list(chart.groupby)
        for m in chart.metrics:
            col = (m.get("column") or {}).get("column_name")
            if col and col not in cols:
                cols.append(col)
        if chart.time_column and chart.time_column not in cols:
            cols.append(chart.time_column)
        col_str = ", ".join(cols)
        if len(col_str) > 30:
            col_str = col_str[:28] + ".."
        table.add_row(chart.title, chart.viz_type, str(chart.width), col_str)

    console.print(table)

    if dashboard_plan.filters:
        filter_names = ", ".join(
            f"{f.column_name} ({f.filter_type})" for f in dashboard_plan.filters
        )
        console.print(f"\n[bold]Filters:[/bold] {filter_names}\n")

    if dashboard_plan.reasoning:
        console.print(f"[dim]Reasoning: {dashboard_plan.reasoning}[/dim]\n")


# ── CLI command ──────────────────────────────────────────────────────────────

@app.command()
def run(
    requirements: Optional[str] = typer.Option(None, help="Inline requirements string"),
    requirements_file: Optional[Path] = typer.Option(None, help="Path to requirements text file"),
    dataset: str = typer.Option(..., help="Superset dataset name"),
    dashboard_title: str = typer.Option(..., help="Dashboard title"),
    dashboard_id: Optional[int] = typer.Option(None, help="Existing dashboard ID (triggers update mode)"),
    superset_url: Optional[str] = typer.Option(None, help="Superset base URL"),
    superset_token: Optional[str] = typer.Option(None, help="Superset API token"),
    superset_username: Optional[str] = typer.Option(None, help="Superset username (overrides .env)"),
    superset_password: Optional[str] = typer.Option(None, help="Superset password (overrides .env)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only, no API calls"),
    preview: bool = typer.Option(False, "--preview", help="Save markdown preview"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    resume_from: Optional[str] = typer.Option(None, help="Resume a failed run by run_id"),
    notify_slack: bool = typer.Option(False, "--notify-slack", help="Send Slack notification on done"),
    notify_email: bool = typer.Option(False, "--notify-email", help="Send email notification on done"),
    verbose: bool = typer.Option(False, "--verbose", help="Print full LLM prompts and responses"),
    client_tag: str = typer.Option("general", help="Tag for catalogue entries (e.g. 'retail', 'saas')"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="LLM model to use (overrides LLM_MODEL in .env)"),
) -> None:
    # ── Resolve requirements text ────────────────────────────────────────────
    if requirements_file:
        requirements_text = requirements_file.read_text()
    elif requirements:
        requirements_text = requirements
    else:
        console.print("[red]Provide --requirements or --requirements-file[/red]")
        raise typer.Exit(1)

    # ── STEP 0: Setup ────────────────────────────────────────────────────────
    if model:
        config.LLM_MODEL = model

    run_id = resume_from or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    state = _load_state(run_id)
    console.rule(f"[bold]Run: {run_id}[/bold]")

    base_url = superset_url or config.SUPERSET_URL
    token = superset_token or config.SUPERSET_TOKEN

    superset_client = SupersetClient(
        base_url=base_url,
        token=token or None,
        username=superset_username or config.SUPERSET_USERNAME,
        password=superset_password or config.SUPERSET_PASSWORD,
    )

    if not token:
        console.print("[cyan]Authenticating with Superset...[/cyan]")
        superset_client.authenticate()

    mode = "update" if dashboard_id else "create"
    console.print(f"Mode: [bold]{mode}[/bold]  |  Dataset: [bold]{dataset}[/bold]")
    _save_state(run_id, state)

    # ── STEP 1: Fetch and enrich dataset ─────────────────────────────────────
    if not _step_done(state, "step1"):
        console.print("\n[bold cyan]Step 1[/bold cyan] — Fetching dataset schema...")
        dataset_info = superset_client.get_dataset_by_name(dataset)
        console.print(f"  Found dataset: [green]{dataset_info.name}[/green] "
                      f"(id={dataset_info.id}, {len(dataset_info.columns)} columns)")

        if not dry_run:
            console.print("  Sampling distinct values for categorical columns...")
            sampler = ColumnSampler(superset_client)
            dataset_info = sampler.enrich_columns(dataset_info)
            enriched = sum(1 for c in dataset_info.columns if c.distinct_values)
            console.print(f"  Enriched {enriched} categorical column(s) with distinct values")

        state["dataset_info"] = dataset_info.model_dump()
        _mark_done(state, "step1")
        _save_state(run_id, state)
    else:
        console.print("[dim]Step 1 — skipped (already completed)[/dim]")
        from models.schemas import DatasetInfo
        dataset_info = DatasetInfo(**state["dataset_info"])

    # ── STEP 2: Fetch existing dashboard (update mode) ────────────────────────
    existing_charts: list[dict] = []
    if mode == "update" and not _step_done(state, "step2"):
        console.print("\n[bold cyan]Step 2[/bold cyan] — Fetching existing dashboard...")
        existing_dash = superset_client.get_dashboard(dashboard_id)
        console.print(f"  Dashboard: [green]{existing_dash.get('dashboard_title')}[/green]")
        existing_charts = superset_client.get_charts_for_dataset(dataset_info.id)
        console.print(f"  Found {len(existing_charts)} existing chart(s) for dataset")
        state["existing_charts"] = existing_charts
        _mark_done(state, "step2")
        _save_state(run_id, state)
    elif mode == "update":
        console.print("[dim]Step 2 — skipped (already completed)[/dim]")
        existing_charts = state.get("existing_charts", [])

    # ── STEP 3: Agent 1 — Parse requirements ─────────────────────────────────
    if not _step_done(state, "step3"):
        console.print("\n[bold cyan]Step 3[/bold cyan] — Parsing requirements (Agent 1)...")
        parsed = requirements_parser.parse_requirements(
            requirements_text, dataset_info, verbose=verbose
        )
        flagged = parsed.get("flagged", [])
        if flagged:
            console.print(f"  [yellow]Flagged requirements ({len(flagged)}):[/yellow]")
            for item in flagged:
                console.print(f"    [yellow]• {item}[/yellow]")
        state["parsed_requirements"] = parsed
        _mark_done(state, "step3")
        _save_state(run_id, state)
    else:
        console.print("[dim]Step 3 — skipped (already completed)[/dim]")
        parsed = state["parsed_requirements"]

    # ── STEP 4: Agent 2 — Plan dashboard ─────────────────────────────────────
    if not _step_done(state, "step4"):
        console.print("\n[bold cyan]Step 4[/bold cyan] — Planning dashboard (Agent 2)...")
        catalogue_manager = CatalogueManager()
        all_intents = " ".join(c.get("intent", "") for c in parsed.get("charts", []))
        similar = catalogue_manager.find_similar(all_intents)
        catalogue_context = catalogue_manager.build_context_string(similar)
        if similar:
            console.print(f"  Found {len(similar)} similar past chart(s) in catalogue")

        dashboard_plan = chart_strategist.plan_dashboard(
            parsed_requirements=parsed,
            dataset_info=dataset_info,
            catalogue_context=catalogue_context,
            dashboard_title=dashboard_title,
            verbose=verbose,
        )
        state["dashboard_plan"] = dashboard_plan.model_dump()
        _mark_done(state, "step4")
        _save_state(run_id, state)
    else:
        console.print("[dim]Step 4 — skipped (already completed)[/dim]")
        dashboard_plan = DashboardPlan(**state["dashboard_plan"])

    # ── STEP 5: Confirm plan ──────────────────────────────────────────────────
    console.print()
    _print_plan(dashboard_plan)

    flagged = parsed.get("flagged", [])
    preview_path: Path | None = None
    if preview or dry_run:
        preview_path = _build_preview(run_id, dashboard_plan, dataset, flagged)
        console.print(f"[dim]Preview saved: {preview_path}[/dim]")

    if dry_run:
        console.print("\n[bold yellow]Dry run complete. No changes made.[/bold yellow]")
        raise typer.Exit(0)

    if not yes:
        proceed = typer.confirm("Proceed with building?", default=True)
        if not proceed:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)

    # ── STEP 6: Build charts ─────────────────────────────────────────────────
    chart_actions: list[tuple[int, str]] = []
    if not _step_done(state, "step6"):
        console.print("\n[bold cyan]Step 6[/bold cyan] — Building charts...")
        n = len(dashboard_plan.charts)
        for i, chart_spec in enumerate(dashboard_plan.charts, 1):
            chart_id, action = superset_client.upsert_chart(
                dataset_info.id, chart_spec, existing_charts
            )
            chart_actions.append((chart_id, action))
            icon = "✓"
            console.print(f"  Chart {i}/{n}: [cyan]{chart_spec.title}[/cyan]  [{action}] {icon}")
        state["chart_actions"] = chart_actions
        _mark_done(state, "step6")
        _save_state(run_id, state)
    else:
        console.print("[dim]Step 6 — skipped (already completed)[/dim]")
        chart_actions = [(item[0], item[1]) for item in state["chart_actions"]]

    # Explicit int cast — state JSON round-trip preserves ints but be defensive
    chart_ids = [int(cid) for cid, _ in chart_actions]

    # ── STEP 7: Build position_json (only after ALL chart IDs are collected) ──
    console.print("\n[bold cyan]Step 7[/bold cyan] — Building layout...")
    position_json = build_position_json(chart_ids, dashboard_plan.charts)

    # Verify IDs match before sending to Superset
    position_chart_ids = [
        v["meta"]["chartId"]
        for v in position_json.values()
        if isinstance(v, dict) and v.get("type") == "CHART"
    ]
    console.print(f"  Chart IDs created   : {chart_ids}")
    console.print(f"  Chart IDs in layout : {position_chart_ids}")
    if sorted(chart_ids) != sorted(position_chart_ids):
        console.print("[red]  WARNING: ID mismatch between created charts and layout![/red]")

    state["position_json"] = position_json
    _save_state(run_id, state)

    # ── STEP 8: Create or update dashboard ───────────────────────────────────
    final_dashboard_id: int
    dashboard_url: str
    if not _step_done(state, "step8"):
        console.print("\n[bold cyan]Step 8[/bold cyan] — Assembling dashboard...")
        if mode == "create":
            final_dashboard_id, dashboard_url = superset_client.create_dashboard(
                dashboard_title, chart_ids, position_json
            )
            console.print(f"  Created dashboard id=[green]{final_dashboard_id}[/green]")
        else:
            dashboard_url = superset_client.update_dashboard(
                dashboard_id, chart_ids, position_json
            )
            final_dashboard_id = dashboard_id
            console.print(f"  Updated dashboard id=[green]{final_dashboard_id}[/green]")
        state["dashboard_id"] = final_dashboard_id
        state["dashboard_url"] = dashboard_url
        _mark_done(state, "step8")
        _save_state(run_id, state)
    else:
        console.print("[dim]Step 8 — skipped (already completed)[/dim]")
        final_dashboard_id = state["dashboard_id"]
        dashboard_url = state["dashboard_url"]

    # ── STEP 9: Set up filter bar ─────────────────────────────────────────────
    if not _step_done(state, "step9"):
        console.print("\n[bold cyan]Step 9[/bold cyan] — Configuring filter bar...")
        superset_client.set_dashboard_filters(
            final_dashboard_id, dashboard_plan.filters, dataset_info.id
        )
        console.print(f"  Configured {len(dashboard_plan.filters)} native filter(s)")
        _mark_done(state, "step9")
        _save_state(run_id, state)
    else:
        console.print("[dim]Step 9 — skipped (already completed)[/dim]")

    # ── STEP 10: QA review ────────────────────────────────────────────────────
    console.print("\n[bold cyan]Step 10[/bold cyan] — Running QA review (Agent 3)...")
    qa_report = qa_reviewer.run_qa(
        dashboard_plan=dashboard_plan,
        dataset_info=dataset_info,
        chart_actions=chart_actions,
        superset_client=superset_client,
        verbose=verbose,
    )
    if qa_report.passed:
        console.print("  [green]✓ All QA checks passed[/green]")
    else:
        console.print(f"  [yellow]⚠  {len(qa_report.issues)} issue(s) found:[/yellow]")
        for issue in qa_report.issues:
            console.print(f"    [yellow]• {issue}[/yellow]")
    if qa_report.suggestions:
        console.print("  Suggestions:")
        for s in qa_report.suggestions:
            console.print(f"    [dim]• {s}[/dim]")

    # ── STEP 11: Update catalogue ─────────────────────────────────────────────
    console.print("\n[bold cyan]Step 11[/bold cyan] — Updating chart catalogue...")
    new_entries: list[CatalogueEntry] = []
    created_pairs = [(spec, action) for spec, (_, action) in
                     zip(dashboard_plan.charts, chart_actions) if action == "created"]
    for spec, _ in created_pairs:
        metric_cols = [
            (m.get("column") or {}).get("column_name", "")
            for m in spec.metrics
            if m.get("expressionType") == "SIMPLE"
        ]
        new_entries.append(
            CatalogueEntry(
                client_hint=client_tag,
                intent=spec.title,
                viz_type=spec.viz_type,
                metric_columns=[c for c in metric_cols if c],
                dimension_columns=spec.groupby,
                time_column=spec.time_column,
                worked_well=qa_report.passed,
                notes=spec.reasoning,
            )
        )
    if new_entries:
        CatalogueManager().append(new_entries)
        console.print(f"  Appended {len(new_entries)} new entry/entries to catalogue")
    else:
        console.print("  No new entries (all charts were updates)")

    # ── STEP 12: Notify ───────────────────────────────────────────────────────
    if notify_slack or notify_email:
        console.print("\n[bold cyan]Step 12[/bold cyan] — Sending notifications...")
        slack_webhook = config.SLACK_WEBHOOK_URL if notify_slack else None
        email_cfg: dict | None = None
        if notify_email and config.NOTIFY_EMAIL_FROM:
            email_cfg = {
                "from_addr": config.NOTIFY_EMAIL_FROM,
                "to_addr": config.NOTIFY_EMAIL_TO,
                "smtp_host": config.NOTIFY_EMAIL_SMTP,
                "smtp_port": config.NOTIFY_EMAIL_PORT,
                "password": config.NOTIFY_EMAIL_PASSWORD,
            }
        notifier = Notifier(slack_webhook=slack_webhook, email_config=email_cfg)
        notifier.notify(
            dashboard_title=dashboard_title,
            dashboard_url=dashboard_url,
            chart_count=len(chart_ids),
            issues=qa_report.issues,
        )

    # ── STEP 13: Final summary ────────────────────────────────────────────────
    created_count = sum(1 for _, a in chart_actions if a == "created")
    updated_count = sum(1 for _, a in chart_actions if a == "updated")

    console.print()
    console.rule()
    console.print(f"  [bold]Dashboard[/bold] : {dashboard_title}")
    console.print(f"  [bold]URL[/bold]       : [link={dashboard_url}]{dashboard_url}[/link]")
    console.print(f"  [bold]Charts[/bold]    : {created_count} created, {updated_count} updated")
    console.print(f"  [bold]Filters[/bold]   : {len(dashboard_plan.filters)} native filter(s) configured")
    console.print(f"  [bold]Issues[/bold]    : {len(qa_report.issues)}")
    if preview_path:
        console.print(f"  [bold]Preview[/bold]   : {preview_path}")
    console.rule()


@app.command("models")
def list_models() -> None:
    """List all models available on your LiteLLM proxy."""
    import httpx
    if not config.LITELLM_BASE_URL:
        console.print("[red]LITELLM_BASE_URL is not set.[/red]")
        raise typer.Exit(1)

    try:
        url = config.LITELLM_BASE_URL.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {config.LITELLM_API_KEY}"}
        resp = httpx.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data", data) if isinstance(data, dict) else data
    except Exception as e:
        console.print(f"[red]Failed to fetch models: {e}[/red]")
        raise typer.Exit(1)

    table = Table(title=f"Models on {config.LITELLM_BASE_URL}", show_lines=True)
    table.add_column("Model ID", style="cyan")

    for m in models:
        model_id = m.get("id", str(m)) if isinstance(m, dict) else str(m)
        table.add_row(model_id)

    console.print(table)
    console.print(f"\n[dim]Active model (from config): [bold]{config.LLM_MODEL}[/bold][/dim]")
    console.print("[dim]Override per run with: --model <model-id>[/dim]")


if __name__ == "__main__":
    app()
