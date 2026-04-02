from __future__ import annotations

import json

from models.schemas import DatasetQAReport, QueryPlan
from tools.llm_client import chat

QA_SYSTEM = """\
You are a SQL structural checker. Apply these rules mechanically:

RULE 1 — Fan-out: If the SQL contains a 1-to-many JOIN (e.g. orders JOIN order_items) \
without aggregation before the join, flag: "Fan-out risk: <table> JOIN may multiply rows."

RULE 2 — NULL in join keys: If a JOIN key column could be NULL (no COALESCE or IS NOT NULL \
filter), flag: "NULL join key: <col> may drop rows silently."

RULE 3 — Division by zero: If any expression divides by a column (x / col), flag: \
"Division by zero risk in expression: <expr>."

RULE 4 — Wrong grain aggregation: If SUM/AVG is applied to a column that looks like \
a count or ratio (e.g. rate, pct, percentage), flag: \
"Wrong aggregation: SUM/AVG of <col> may be incorrect."

Apply only rules where the evidence is explicit in the SQL text. Do NOT flag speculatively.
Return ONLY valid JSON:
{"issues": ["..."], "suggestions": ["..."]}
If no rules fire: {"issues": [], "suggestions": []}
No markdown, no preamble.
"""


class DatasetQA:
    """Phase 2, Agent 2.

    Runs the generated SQL against the live database, checks row counts,
    checks for duplicates, then asks the LLM to review for structural issues.
    Returns a DatasetQAReport.
    """

    def run(self, query_plan: QueryPlan, db_connector) -> DatasetQAReport:
        # ── Step 1: Run the query ─────────────────────────────────────────────
        ok, rows, run_err = db_connector.run_query(query_plan.sql, limit=500)
        if not ok:
            return DatasetQAReport(
                passed=False,
                row_count=0,
                duplicate_row_count=0,
                issues=[f"Query execution failed: {run_err}"],
                suggestions=["Fix the SQL syntax or connection, then re-generate."],
                sample_rows=[],
            )

        sample_rows = rows[:5]

        # ── Step 2: Row count ─────────────────────────────────────────────────
        ok_count, row_count, count_err = db_connector.get_row_count(query_plan.sql)
        if not ok_count:
            row_count = len(rows)  # fallback to limit-500 result length

        # ── Step 3: Duplicate check ───────────────────────────────────────────
        ok_dup, dup_count, dup_err = db_connector.check_duplicates(query_plan.sql)
        if not ok_dup:
            dup_count = 0

        # ── Step 4: LLM structural review ────────────────────────────────────
        # Truncate sample rows to avoid token overflow
        sample_preview = json.dumps(sample_rows[:5], default=str)[:2000]

        user_message = (
            f"SQL:\n{query_plan.sql}\n\n"
            f"Row count: {row_count}\n"
            f"Duplicate rows: {dup_count}\n"
            f"Sample rows (up to 5):\n{sample_preview}"
        )

        llm_issues: list[str] = []
        llm_suggestions: list[str] = []
        last_error = ""

        for attempt in range(3):
            msg = user_message
            if last_error:
                msg += (
                    f"\n\nYour previous response had a JSON parse error: {last_error}"
                    "\nReturn ONLY valid JSON."
                )

            text = chat(QA_SYSTEM, msg, temperature=0)

            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            try:
                data = json.loads(text)
                llm_issues = data.get("issues", [])
                llm_suggestions = data.get("suggestions", [])
                break
            except json.JSONDecodeError as exc:
                last_error = str(exc)

        # ── Step 5: Combine results ───────────────────────────────────────────
        all_issues: list[str] = []
        if dup_count > 0:
            all_issues.append(
                f"Duplicate rows detected: {dup_count} out of {row_count} rows are duplicates."
            )
        all_issues.extend(llm_issues)

        passed = dup_count == 0 and not any(
            "fan-out" in i.lower() or "critical" in i.lower() for i in llm_issues
        )

        return DatasetQAReport(
            passed=passed,
            row_count=row_count,
            duplicate_row_count=dup_count,
            issues=all_issues,
            suggestions=llm_suggestions,
            sample_rows=sample_rows,
        )
