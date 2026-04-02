from __future__ import annotations

import json

from models.schemas import DashboardPlan, DatasetInfo
from tools.llm_client import chat

SYSTEM_PROMPT = """\
You are a data visualization expert building an Apache Superset dashboard.

You have access to:
1. A list of grounded chart intents with exact column names
2. Dataset column details including categorical value samples
3. A catalogue of past chart specs that worked well for similar intents

For each chart intent:
- Choose the best viz_type using the rules below
- Build the correct metrics list using SIMPLE aggregation objects
- Set groupby, time_column, time_grain where relevant
- Assign a width: 3 for KPIs, 6 for pies/small bars, 12 for trends/tables
- Write a one-sentence reasoning explaining the chart type choice

For the filter bar:
- Convert each entry in filter_bar from the parsed requirements into
  a FilterSpec with the correct filter_type

Width rules (strict — do not deviate):
- big_number_total → width 3
- echarts_timeseries_line → width 12
- bar (≤6 categories) → width 6
- bar (>6 categories) → width 12
- pie → width 6
- table → width 12
- scatter → width 12

viz_type selection rules:
- Single headline number → big_number_total
- Trend over time → echarts_timeseries_line
- Ranking/comparison, few categories → bar
- Part-of-whole, ≤6 slices → pie
- Leaderboard or detailed data → table
- Two numeric columns correlated → scatter

SIMPLE metric object format:
{
  "expressionType": "SIMPLE",
  "column": {"column_name": "<col>"},
  "aggregate": "SUM",
  "label": "SUM(<col>)"
}

For COUNT(*) use:
{
  "expressionType": "SIMPLE",
  "column": {"column_name": "id"},
  "aggregate": "COUNT",
  "label": "COUNT(*)"
}

Return ONLY valid JSON — no markdown, no preamble.

Output schema:
{
  "dashboard_title": "Sales Dashboard",
  "reasoning": "One sentence about the overall dashboard approach.",
  "charts": [
    {
      "title": "Total Revenue",
      "viz_type": "big_number_total",
      "metrics": [{"expressionType": "SIMPLE", "column": {"column_name": "revenue"}, "aggregate": "SUM", "label": "SUM(revenue)"}],
      "groupby": [],
      "time_column": null,
      "time_grain": null,
      "filters": [],
      "row_limit": null,
      "sort_by": null,
      "reasoning": "Single KPI card gives a headline revenue number.",
      "width": 3
    }
  ],
  "filters": [
    {
      "column_name": "region",
      "filter_type": "categorical",
      "default_value": null,
      "label": "Region"
    }
  ]
}
"""


def plan_dashboard(
    parsed_requirements: dict,
    dataset_info: DatasetInfo,
    catalogue_context: str,
    dashboard_title: str,
    verbose: bool = False,
) -> DashboardPlan:
    column_summary = []
    for col in dataset_info.columns:
        line = f"- {col.column_name} ({col.type})"
        if col.distinct_values:
            line += f" — values: {', '.join(col.distinct_values)}"
        elif col.type == "STRING":
            line += " — high cardinality"
        column_summary.append(line)

    user_message = (
        f"Dashboard title: {dashboard_title}\n\n"
        f"Parsed requirements:\n{json.dumps(parsed_requirements, indent=2)}\n\n"
        f"Dataset columns:\n" + "\n".join(column_summary)
    )

    if catalogue_context:
        user_message += f"\n\n{catalogue_context}"

    if verbose:
        from rich.console import Console
        Console().print(f"[dim]--- Agent 2 prompt ---\n{user_message}\n[/dim]")

    last_error = ""
    for attempt in range(3):
        prompt = user_message
        if last_error:
            prompt += f"\n\nYour previous response had a JSON parse error: {last_error}\nReturn ONLY valid JSON."

        text = chat(SYSTEM_PROMPT, prompt)

        if verbose:
            from rich.console import Console
            Console().print(f"[dim]--- Agent 2 response (attempt {attempt + 1}) ---\n{text}\n[/dim]")

        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            data = json.loads(text)
            data["position_json"] = {}
            # Normalize sort_by: LLM sometimes returns a dict instead of a list
            for chart in data.get("charts", []):
                if isinstance(chart.get("sort_by"), dict):
                    chart["sort_by"] = [chart["sort_by"]]
            return DashboardPlan(**data)
        except (json.JSONDecodeError, Exception) as e:
            last_error = str(e)

    raise RuntimeError(
        f"Agent 2 (Chart Strategist) failed after 3 attempts. Last error: {last_error}"
    )


class ChartStrategist:
    """Class wrapper so Streamlit app can call strategist.run(parsed_reqs, dataset_info, catalogue)."""

    def run(
        self,
        parsed_requirements: dict,
        dataset_info: DatasetInfo,
        catalogue,
        dashboard_title: str = "Dashboard",
    ) -> DashboardPlan:
        from tools.catalogue import CatalogueManager
        all_intents = " ".join(c.get("intent", "") for c in parsed_requirements.get("charts", []))
        similar = catalogue.find_similar(all_intents)
        catalogue_context = catalogue.build_context_string(similar)
        return plan_dashboard(
            parsed_requirements=parsed_requirements,
            dataset_info=dataset_info,
            catalogue_context=catalogue_context,
            dashboard_title=dashboard_title,
        )
