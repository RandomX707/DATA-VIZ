from __future__ import annotations

import json

from models.schemas import SchemaMap, TableProfile
from tools.llm_client import chat

SYSTEM_PROMPT = """\
You are a senior data analyst selecting exactly which database tables and columns are \
needed to answer a business requirement.

CORE SELECTION PRINCIPLE: Only include a table if the prompt requires a column that \
exists in that table but does not exist in the fact table. Ask yourself for each \
candidate table: does adding this table give me a column I cannot get from tables \
already selected? If no, exclude it.

The most common legitimate reason to add a dimension table is to get a human-readable \
label that the fact table only has as an ID. For example: fact table has project_id but \
prompt asks to group by project — include projects to get project_name.

Do NOT include a table just because it has a FK relationship to the fact table. FK \
relationships are common — most dimension tables in any schema will join to the fact \
table. Joining capability alone is not a reason to include a table.

Only include error_logs, audit_logs, or similar secondary fact tables if the prompt \
explicitly asks for data that cannot be derived from the primary fact table.

INCLUSION RULES — include a table if ANY of these are true:

RULE A — Direct match: The table name or any of its column names contain keywords from \
the business prompt. Be liberal with matching — synonyms count. "requests" matches \
api_requests. "errors" matches status_code, error_code, error_logs. "endpoints" matches \
endpoint column. "response time" matches response_time_ms.

RULE B — Fact table: It has the highest row count. Always include.

RULE C — Label gap: The fact table has an X_id column, the prompt needs to display or \
group by X (not just filter on X_id), and only the X table has the label column. \
Include the X table. Do not include it if the fact table already has a name/label \
column that satisfies the prompt.

RULE D — Time dimension: If the prompt mentions any time-based analysis (trend, over \
time, by day, by month, daily, weekly, patterns over time) AND a table contains a \
primary date/time column not already present in the fact table, include it.

EXCLUSION RULES — exclude a table if ANY of these are true:
- It is a pure system/audit table (audit_logs, migrations, schema_versions, *_archive, \
*_backup, *_temp, *_tmp, sessions, tokens) and the prompt does not mention it
- Every column it provides is already available (directly or via a label) from already \
selected tables
- The prompt does not require any column unique to this table

COLUMN SELECTION RULES:
- From the fact table: include ALL columns. Never exclude fact table columns — the \
query architect needs full flexibility.
- From dimension tables: include the primary key, any name/label columns \
(e.g. org_name, project_name), and any columns mentioned in the prompt.
- From date tables or time columns: always include them if any time-based analysis \
is requested.
- Exclude columns that are clearly irrelevant: internal system fields like \
created_by_system, internal_flags, raw_payload unless mentioned in the prompt.

PRIMARY TABLE RULE:
- The suggested_primary must always be the table with the highest row_count among \
selected tables. Never pick a dimension table as primary.

Return ONLY valid JSON with these exact keys:
{
  "suggested_primary": "table_name",
  "selected_tables": ["table1", "table2"],
  "suggested_joins": ["JOIN table2 ON table1.fk = table2.pk"],
  "agent_reasoning": "one paragraph explaining selections"
}
No markdown, no preamble.
"""

MIN_TABLES = 2


def _format_table_for_prompt(table: TableProfile) -> str:
    lines = [
        f"Table: {table.table_name}",
        f"Row count: {table.row_count:,}",
        "Columns:",
    ]
    for col in table.columns:
        flags = " ".join(filter(None, [
            "[PK]" if col.is_likely_pk else "",
            "[FK]" if col.is_likely_fk else "",
            "[DATE]" if col.is_likely_date else "",
        ]))
        sample_str = (
            f"  Sample: {', '.join(col.sample_values[:3])}"
            if col.sample_values
            else ""
        )
        lines.append(
            f"  - {col.column_name} ({col.data_type})"
            f" [null: {col.null_pct:.0f}%] {flags}{sample_str}"
        )
    lines.append("---")
    return "\n".join(lines)


class ContextAnalyst:
    """Phase 1, Agent 2.

    Receives profiled tables, selects the relevant ones, identifies the fact
    table, suggests joins, and returns a SchemaMap.
    Tables are sorted by row_count descending before being passed to the LLM
    so the fact table always appears first (reinforces PRIMARY TABLE RULE).
    Post-processing enforces: primary = highest row-count selected, and
    minimum table count of MIN_TABLES.
    """

    def run(self, business_prompt: str, profiled_tables: list[TableProfile]) -> SchemaMap:
        all_table_names = [t.table_name for t in profiled_tables]

        # Sort by row_count descending so fact table appears first in prompt
        sorted_tables = sorted(profiled_tables, key=lambda t: t.row_count, reverse=True)

        tables_description = "\n\n".join(
            _format_table_for_prompt(t) for t in sorted_tables
        )
        user_message = (
            f"Business prompt: {business_prompt}\n\n"
            f"Profiled tables (sorted by row count, highest first):\n"
            f"{tables_description}"
        )

        last_error = ""
        result: dict = {}

        for attempt in range(3):
            msg = user_message
            if last_error:
                msg += (
                    f"\n\nYour previous response had a JSON parse error: {last_error}"
                    "\nReturn ONLY valid JSON."
                )

            text = chat(SYSTEM_PROMPT, msg, temperature=0)

            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            try:
                result = json.loads(text)
                break
            except (json.JSONDecodeError, Exception) as exc:
                last_error = str(exc)
                result = {}

        # ── Fallback if all attempts failed ──────────────────────────────────
        if not result:
            fallback_primary = (
                max(profiled_tables, key=lambda t: t.row_count).table_name
                if profiled_tables else ""
            )
            return SchemaMap(
                all_tables=all_table_names,
                profiled_tables=profiled_tables,
                suggested_primary=fallback_primary,
                suggested_joins=[],
                agent_reasoning="Context analysis failed; all profiled tables included.",
            )

        # ── Determinism enforcement: primary = highest row-count selected ─────
        selected_names: list[str] = result.get("selected_tables", all_table_names[:])
        selected_profiles = [t for t in profiled_tables if t.table_name in selected_names]
        if not selected_profiles:
            selected_profiles = profiled_tables[:]
            selected_names = [t.table_name for t in selected_profiles]

        highest_rowcount_table = max(selected_profiles, key=lambda t: t.row_count).table_name
        result["suggested_primary"] = highest_rowcount_table
        if highest_rowcount_table not in selected_names:
            selected_names.append(highest_rowcount_table)
        result["selected_tables"] = selected_names

        # ── Minimum table count enforcement ───────────────────────────────────
        if len(result["selected_tables"]) < MIN_TABLES:
            all_sorted = sorted(profiled_tables, key=lambda t: t.row_count, reverse=True)
            for t in all_sorted:
                if t.table_name not in result["selected_tables"]:
                    result["selected_tables"].append(t.table_name)
                if len(result["selected_tables"]) >= MIN_TABLES:
                    break

        # ── Rebuild selected_profiles from final selected_tables list ─────────
        final_selected_profiles = [
            t for t in profiled_tables if t.table_name in result["selected_tables"]
        ]
        if not final_selected_profiles:
            final_selected_profiles = profiled_tables

        return SchemaMap(
            all_tables=all_table_names,
            profiled_tables=final_selected_profiles,
            suggested_primary=result["suggested_primary"],
            suggested_joins=result.get("suggested_joins", []),
            agent_reasoning=result.get("agent_reasoning", ""),
        )
