from __future__ import annotations

import json

from models.schemas import DashboardPlan, DatasetInfo, QAReport
from tools.llm_client import chat
from tools.superset_api import SupersetClient

SYSTEM_PROMPT = """\
You are a QA reviewer for Superset dashboards. You will receive:
1. A dashboard plan with chart specs
2. Dataset column information
3. A list of chart IDs and their creation actions

Check for:
- Are all major stakeholder requirements covered by at least one chart?
- Any chart type mismatches given the data (e.g. trend chart on a non-time column)?
- Any calculated columns referenced but missing from dataset?
- Any SUM/AVG aggregate applied to a non-numeric column?

Return ONLY valid JSON — no markdown, no preamble.

Output schema:
{
  "passed": true,
  "issues": [],
  "suggestions": ["Consider adding a time filter for the date range."]
}
"""


def run_qa(
    dashboard_plan: DashboardPlan,
    dataset_info: DatasetInfo,
    chart_actions: list[tuple[int, str]],
    superset_client: SupersetClient,
    verbose: bool = False,
) -> QAReport:
    column_names = {c.column_name for c in dataset_info.columns}
    numeric_columns = {c.column_name for c in dataset_info.columns if c.type == "NUMERIC"}

    issues: list[str] = []

    for chart_id, _ in chart_actions:
        try:
            superset_client._request("GET", f"/api/v1/chart/{chart_id}")
        except Exception as e:
            issues.append(f"Chart ID {chart_id} could not be verified: {e}")

    for chart in dashboard_plan.charts:
        for col in chart.groupby:
            if col not in column_names:
                issues.append(
                    f"Chart '{chart.title}': groupby column '{col}' not found in dataset"
                )
        for metric in chart.metrics:
            if metric.get("expressionType") == "SIMPLE":
                col = (metric.get("column") or {}).get("column_name", "")
                agg = metric.get("aggregate", "")
                if col and col not in column_names and agg != "COUNT":
                    issues.append(
                        f"Chart '{chart.title}': metric column '{col}' not found in dataset"
                    )
                if agg in ("SUM", "AVG") and col and col not in numeric_columns:
                    issues.append(
                        f"Chart '{chart.title}': {agg} aggregate applied to non-numeric column '{col}'"
                    )
        if chart.time_column and chart.time_column not in column_names:
            issues.append(
                f"Chart '{chart.title}': time_column '{chart.time_column}' not found in dataset"
            )

    for f in dashboard_plan.filters:
        if f.column_name not in column_names:
            issues.append(
                f"Filter '{f.label}': column '{f.column_name}' not found in dataset"
            )

    plan_summary = {
        "charts": [
            {
                "title": c.title,
                "viz_type": c.viz_type,
                "metrics": c.metrics,
                "groupby": c.groupby,
                "time_column": c.time_column,
                "reasoning": c.reasoning,
            }
            for c in dashboard_plan.charts
        ],
        "filters": [f.model_dump() for f in dashboard_plan.filters],
        "rule_based_issues_found": issues,
    }

    user_message = (
        f"Dashboard: {dashboard_plan.dashboard_title}\n\n"
        f"Plan summary:\n{json.dumps(plan_summary, indent=2)}\n\n"
        f"Dataset columns: {', '.join(column_names)}\n\n"
        f"Chart actions: {chart_actions}\n\n"
        "Please check for requirement coverage gaps and type mismatches."
    )

    if verbose:
        from rich.console import Console
        Console().print(f"[dim]--- Agent 3 prompt ---\n{user_message}\n[/dim]")

    last_error = ""
    for attempt in range(3):
        prompt = user_message
        if last_error:
            prompt += f"\n\nPrevious JSON parse error: {last_error}\nReturn ONLY valid JSON."

        text = chat(SYSTEM_PROMPT, prompt, max_tokens=2048)

        if verbose:
            from rich.console import Console
            Console().print(f"[dim]--- Agent 3 response (attempt {attempt + 1}) ---\n{text}\n[/dim]")

        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            data = json.loads(text)
            llm_issues: list[str] = data.get("issues", [])
            all_issues = issues + llm_issues
            return QAReport(
                passed=len(all_issues) == 0,
                issues=all_issues,
                suggestions=data.get("suggestions", []),
            )
        except (json.JSONDecodeError, Exception) as e:
            last_error = str(e)

    return QAReport(
        passed=len(issues) == 0,
        issues=issues,
        suggestions=["QA LLM check failed; rule-based checks only were applied."],
    )
