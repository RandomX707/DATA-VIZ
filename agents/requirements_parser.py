from __future__ import annotations

import json

from models.schemas import DatasetInfo
from tools.llm_client import chat

SYSTEM_PROMPT = """\
You are a data analyst assistant. You receive stakeholder requirements
and a full description of available dataset columns including, for
categorical columns, their actual distinct values.

Your job:
1. Parse each requirement into a concrete chart request
2. Ground every metric and dimension to an exact column name from
   the provided column list — never invent column names
3. For filter columns, use the distinct_values to suggest sensible
   default filter values where appropriate
4. If a requirement cannot be satisfied by available columns,
   add it to the "flagged" list with a clear explanation
5. Return ONLY valid JSON — no markdown, no preamble

Output schema (return exactly this structure):
{
  "charts": [
    {
      "intent": "monthly revenue trend",
      "metric_columns": ["revenue"],
      "aggregate": "SUM",
      "dimension_columns": [],
      "time_column": "order_date",
      "time_grain": "monthly",
      "filter_columns": [],
      "suggested_width": 12,
      "notes": ""
    }
  ],
  "filter_bar": [
    {
      "column_name": "region",
      "filter_type": "categorical",
      "label": "Region",
      "default_value": null
    }
  ],
  "flagged": [
    "forecast line requested but no forecast column found in dataset"
  ]
}

filter_type must be one of: "time", "categorical", "numerical"
time_grain must be one of: "PT1M", "PT1H", "P1D", "P1W", "P1M", "P3M", "P1Y" or null
suggested_width must be one of: 3, 6, 12
"""


def _build_column_description(dataset_info: DatasetInfo) -> str:
    lines = ["Available columns:"]
    for col in dataset_info.columns:
        if col.is_dttm or col.type == "DATETIME":
            tag = "(DATETIME, time column)"
        elif col.type == "NUMERIC":
            tag = "(NUMERIC)"
        else:
            tag = "(STRING)"

        if col.distinct_values:
            values_str = ", ".join(col.distinct_values)
            tag += f" — values: {values_str}"
        elif col.type == "STRING":
            tag += " — high cardinality"

        lines.append(f"- {col.column_name} {tag}")

    if dataset_info.metrics:
        lines.append("\nPre-defined dataset metrics:")
        for m in dataset_info.metrics:
            lines.append(f"- {m.get('metric_name')} ({m.get('expression', '')})")

    return "\n".join(lines)


def parse_requirements(
    requirements: str,
    dataset_info: DatasetInfo,
    verbose: bool = False,
) -> dict:
    column_desc = _build_column_description(dataset_info)
    user_message = (
        f"Stakeholder requirements:\n{requirements}\n\n"
        f"{column_desc}"
    )

    if verbose:
        from rich.console import Console
        Console().print(f"[dim]--- Agent 1 prompt ---\n{user_message}\n[/dim]")

    last_error = ""
    for attempt in range(3):
        prompt = user_message
        if last_error:
            prompt += f"\n\nYour previous response had a JSON parse error: {last_error}\nReturn ONLY valid JSON."

        text = chat(SYSTEM_PROMPT, prompt)

        if verbose:
            from rich.console import Console
            Console().print(f"[dim]--- Agent 1 response (attempt {attempt + 1}) ---\n{text}\n[/dim]")

        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            last_error = str(e)

    raise RuntimeError(
        f"Agent 1 (Requirements Parser) failed to return valid JSON after 3 attempts. "
        f"Last error: {last_error}"
    )
