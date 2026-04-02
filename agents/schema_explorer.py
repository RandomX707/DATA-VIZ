from __future__ import annotations

import json

from models.schemas import TableProfile
from tools.llm_client import chat

SHORTLIST_SYSTEM = """\
You are a data analyst selecting database tables relevant to a business requirement.
Apply these rules in order — they are mandatory, not suggestions:

RULE 1 — ALWAYS include a table if its name or columns contain keywords that directly \
match nouns in the business prompt. For example, if the prompt mentions "revenue" or \
"invoices", include any table named invoices, billing, payments, or transactions. If the \
prompt mentions "users" or "employees", include tables named users, employees, staff, members.

RULE 2 — ALWAYS include the highest row-count table in the schema. This is almost always \
the primary fact table.

RULE 3 — ALWAYS include tables that are likely dimension tables for the fact table — i.e. \
tables whose primary key appears as a foreign key column in the fact table. You can identify \
these by matching column names: if the fact table has a column called org_id, include the \
table whose PK is org_id (likely named organizations or orgs).

RULE 4 — EXCLUDE a table ONLY if its name exactly matches one of these system/utility \
patterns and it was NOT mentioned in the prompt:
- Exact names: migrations, schema_versions, ar_internal_metadata, audit_logs, audit_trail, \
change_log, sessions, refresh_tokens, password_resets
- Names ending in: _archive, _backup, _tmp, _temp, _bak
Do NOT exclude a table just because its name doesn't appear in the prompt. Business tables \
often have names that don't match prompt keywords directly.

RULE 5 — Default to INCLUDE. When the schema has more than 10 tables, aim to shortlist \
30–50% of them (never fewer than 3). Do not apply stricter filtering just because the \
prompt is short or specific.

RULE 6 — Always trace FK chains up to 2 levels deep. If a table you are including has \
a column named X_id, also include the table named X, Xs, or X_table. Then for each of \
those tables, if they have their own FK columns, include those referenced tables too. \
Stop at 2 levels.

Apply all rules and return ONLY valid JSON:
{"tables": ["name1", "name2", ...]}
No markdown, no preamble, no explanation.
"""


class SchemaExplorer:
    """Phase 1, Agent 1.

    Fetches all tables from the database and profiles the relevant ones.
    - If ≤ 15 tables: profiles all of them.
    - If > 15 tables: uses LLM to shortlist 8–10 candidates first.
    """

    def run(
        self, business_prompt: str, db_connector  # DBConnector, avoid circular import
    ) -> list[TableProfile]:
        all_tables = db_connector.get_all_tables()

        if len(all_tables) <= 15:
            candidate_tables = all_tables
        else:
            candidate_tables = self._shortlist_tables(business_prompt, all_tables)

        profiles: list[TableProfile] = []
        for table_name in candidate_tables:
            try:
                profile = db_connector.profile_table(table_name)
                profiles.append(profile)
            except Exception:
                pass  # skip tables that can't be profiled (permissions, etc.)

        return profiles

    def _shortlist_tables(self, prompt: str, all_tables: list[str]) -> list[str]:
        user_message = (
            f"Business prompt: {prompt}\n"
            f"All tables: {json.dumps(all_tables)}"
        )

        last_error = ""
        for attempt in range(3):
            msg = user_message
            if last_error:
                msg += (
                    f"\n\nYour previous response had a JSON parse error: {last_error}"
                    "\nReturn ONLY valid JSON."
                )

            text = chat(SHORTLIST_SYSTEM, msg, temperature=0)

            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            try:
                data = json.loads(text)
                tables = data.get("tables", [])
                # Validate — only return names that actually exist
                valid = [t for t in tables if t in all_tables]
                return valid if valid else all_tables[:10]
            except json.JSONDecodeError as exc:
                last_error = str(exc)

        # Fallback: first 10 tables alphabetically
        return all_tables[:10]
