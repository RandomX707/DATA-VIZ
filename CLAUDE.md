# Superset Dashboard Builder — Project Context

## What This Project Does

A Python CLI tool that automates Apache Superset dashboard creation end-to-end.
The user provides a dataset name (already in Superset) and plain-text stakeholder
requirements. The tool uses an LLM to plan charts, then creates them via the
Superset REST API, assembles a dashboard, sets up native filters, runs QA, and
optionally notifies via Slack or email.

---

## Environment

- **Python**: 3.10.12
- **Apache Superset**: 5.0.0 (running locally at http://127.0.0.1:8088)
- **Superset admin user**: `admin` (password stored in `.env`)
- **Superset config**: `~/.superset/superset_config.py`
- **LLM**: `claude-haiku-4-5` via LiteLLM proxy (OpenAI-compatible API, `openai` SDK)
- **Key dependency fix**: `marshmallow` must stay on `3.x` — Superset 5.0.0 is
  incompatible with marshmallow 4.x (causes `TypeError: Field.__init__() got an
  unexpected keyword argument 'minLength'`)

---

## Project Structure

```
superset_dashboard_builder/
├── main.py                    # CLI entrypoint (typer), 13-step orchestrator
├── config.py                  # Loads .env into a Config singleton
├── agents/
│   ├── requirements_parser.py # Agent 1: parses plain-text requirements → grounded JSON
│   ├── chart_strategist.py    # Agent 2: plans charts + filters → DashboardPlan
│   └── qa_reviewer.py         # Agent 3: rule-based + LLM QA → QAReport
├── tools/
│   ├── superset_api.py        # SupersetClient, build_position_json, build_chart_params
│   ├── column_sampler.py      # Samples distinct values for low-cardinality string cols
│   ├── catalogue.py           # Manages charts_catalogue.json across runs
│   └── notifier.py            # Slack webhook + SMTP email (both optional)
├── models/
│   └── schemas.py             # All Pydantic v2 models
├── runs/                      # One JSON state file per run (for resume)
├── previews/                  # Markdown dashboard previews
├── charts_catalogue.json      # Grows over time; stores successful chart specs
├── .env.example               # Template — copy to .env and fill in
└── requirements.txt
```

---

## Pydantic Models (models/schemas.py)

| Model | Purpose |
|-------|---------|
| `DatasetColumn` | One column: name, type, is_dttm, expression, distinct_values |
| `DatasetInfo` | Full dataset: id, name, columns list, metrics list |
| `FilterSpec` | One native filter: column, filter_type, default_value, label |
| `ChartSpec` | One chart: title, viz_type, metrics, groupby, time fields, width, reasoning |
| `DashboardPlan` | Full plan: title, charts list, filters list, position_json, reasoning |
| `QAReport` | QA result: passed bool, issues list, suggestions list |
| `CatalogueEntry` | Catalogue record: client_hint, intent, viz_type, columns, worked_well, notes |

---

## Tools

### tools/superset_api.py

**`SupersetClient`** — all HTTP calls go through `_request()` which handles:
- 401 → re-authenticate once, retry
- Non-2xx → raise `RuntimeError` with full response body

Key methods:
- `authenticate()` — POST login + fetch CSRF token, stores both in `self.headers`
- `get_dataset_by_name(name)` — Rison-encoded filter query; tries `table_name` then `datasource_name`
- `get_dataset_columns(id)` — normalises raw type strings to STRING/NUMERIC/DATETIME
- `get_charts_for_dataset(id)` — used before upsert to find existing charts
- `upsert_chart(dataset_id, spec, existing)` — deduplicates by title; updates if exists, creates if not
- `create_dashboard / update_dashboard` — POST then PUT with `position_json` as JSON string
- `set_dashboard_filters(id, filters, dataset_id)` — PUT `json_metadata` with native filter config;
  must include `filter_sets_configuration` and `default_filters` keys or Superset silently ignores it

**`build_position_json(chart_ids, chart_specs)`** — packs charts into 12-col rows using each
chart's `width` (3/6/12). Returns valid Superset v2 `position_json` tree.

**`build_chart_params(chart_spec)`** — returns the `params` dict for each viz type.

**`VIZ_TYPE_MAP`** — maps spec names to Superset 5.x internal names:
```python
"bar"     → "dist_bar"
"scatter" → "echarts_scatter"
```

**`FORCED_WIDTHS`** — post-LLM enforcement to prevent row-packing bugs:
```python
"big_number_total": 3
"echarts_timeseries_line": 12
"table": 12
"echarts_scatter": 12
```

### tools/column_sampler.py

`ColumnSampler.enrich_columns(dataset_info)`:
- For each STRING column: runs `SELECT DISTINCT col LIMIT 21` via `/api/v1/sqllab/execute/`
- ≤20 results → stores in `column.distinct_values`
- 21 results → high cardinality, leaves as `None`
- Each column wrapped in try/except — never crashes the pipeline
- Handles both physical tables and virtual datasets (with SQL)

### tools/catalogue.py

`CatalogueManager` reads/writes `charts_catalogue.json`:
- `find_similar(intent)` — keyword overlap scoring, returns top-N entries
- `build_context_string(entries)` — formats entries for injection into Agent 2 prompt
- Only charts with `action="created"` are appended (not updates)

### tools/notifier.py

`Notifier.notify(...)` — entirely wrapped in try/except, never raises.
- Slack: POST to webhook with mrkdwn block
- Email: smtplib with STARTTLS

---

## Agents (LLM Calls)

All three agents share a single helper: `tools/llm_client.py` → `chat(system, user)`.
This uses the `openai` SDK pointed at the LiteLLM proxy (`LITELLM_BASE_URL`).

All three agents follow the same pattern:
1. Build a prompt with grounded data
2. Call `chat(SYSTEM_PROMPT, user_message)` → returns plain text
3. Strip markdown fences if present
4. `json.loads()` — on failure, retry up to 3x feeding the error back
5. Return parsed dict / Pydantic model

### Agent 1 — requirements_parser.py
- Input: raw requirements text + enriched `DatasetInfo`
- Grounds every column reference to real column names
- Flags requirements that can't be satisfied
- Output schema: `{charts: [...], filter_bar: [...], flagged: [...]}`

### Agent 2 — chart_strategist.py
- Input: parsed requirements + DatasetInfo + catalogue context string
- Selects viz_type, builds metrics list, assigns width
- Does NOT output `position_json` — that's built by the orchestrator after chart creation
- Output: `DashboardPlan` (without position_json)

### Agent 3 — qa_reviewer.py
- Rule-based checks first (no LLM): column existence, SUM on non-numeric, filter columns
- Then LLM check: requirement coverage, type mismatches
- Verifies each chart_id exists via GET `/api/v1/chart/{id}`
- Returns `QAReport`

---

## Orchestrator (main.py)

### CLI Usage

```bash
python3 main.py run \
  --requirements "..." \
  --dataset "dataset_name" \
  --dashboard-title "My Dashboard" \
  [--dashboard-id 42]        # triggers update mode \
  [--dry-run]                # plan only, no API calls \
  [--preview]                # save markdown to previews/ \
  [--yes]                    # skip confirmation \
  [--resume-from run_id]     # resume failed run \
  [--notify-slack]           \
  [--notify-email]           \
  [--verbose]                # print full LLM prompts \
  [--client-tag "retail"]
```

### 13-Step Flow

| Step | What happens |
|------|-------------|
| 0 | Setup: load config, authenticate, determine create/update mode, init state file |
| 1 | Fetch dataset by name, enrich columns with distinct values |
| 2 | (Update mode only) fetch existing dashboard + charts for dedup |
| 3 | Agent 1: parse requirements |
| 4 | Agent 2: plan dashboard (with catalogue context) |
| 5 | Print rich confirmation table; optionally save preview; prompt unless --yes |
| 6 | Upsert each chart (create or update by title match) |
| 7 | Build position_json with real chart_ids |
| 8 | Create or update dashboard |
| 9 | Set native filter bar |
| 10 | Agent 3: QA review |
| 11 | Append created charts to catalogue |
| 12 | Notify (Slack/email) |
| 13 | Print final summary |

**Resume**: state is saved to `runs/{run_id}.json` after every step. Pass
`--resume-from run_id` to skip completed steps.

---

## Known Superset 5.x Gotchas (Already Handled)

1. **`bar` → `dist_bar`** and **`scatter` → `echarts_scatter`**: mapped in `VIZ_TYPE_MAP`
2. **`position_json` must be a JSON string**: passed as `json.dumps(position_json)` in PUT body
3. **`json_metadata` must be a JSON string**: same — `json.dumps({...})`
4. **Native filters silently ignored** if `filter_sets_configuration` and `default_filters`
   are missing from `json_metadata` — both are always included in `set_dashboard_filters`
5. **Rison filter URLs must be encoded**: all `?q=` params go through `urllib.parse.quote`
6. **`/api/v1/dataset/{id}/column/{col}/values` does not exist in v5**: sampler uses
   sqllab execute fallback instead
7. **marshmallow must stay on 3.x**: pinned in requirements.txt

---

## .env Keys

```
LITELLM_API_KEY       # required — your LiteLLM proxy key
LITELLM_BASE_URL      # required — e.g. https://litellm.yourcompany.com
LLM_MODEL             # default: claude-haiku-4-5 (any model available on your proxy)
SUPERSET_URL          # default: http://localhost:8088
SUPERSET_TOKEN        # optional; if blank, username/password auth is used
SUPERSET_USERNAME     # default: admin
SUPERSET_PASSWORD
SLACK_WEBHOOK_URL     # optional
NOTIFY_EMAIL_FROM     # optional
NOTIFY_EMAIL_TO       # optional
NOTIFY_EMAIL_SMTP     # default: smtp.gmail.com
NOTIFY_EMAIL_PORT     # default: 587
NOTIFY_EMAIL_PASSWORD # optional
```

---

## Implementation Rules (enforced in code)

- All HTTP calls go through `SupersetClient._request()` — no raw httpx elsewhere
- `column_sampler.enrich_columns()` wraps each column in try/except
- `notifier.notify()` is entirely wrapped in try/except
- `build_position_json()` is called by orchestrator after chart creation, never inside Agent 2
- Only `action="created"` charts are written to catalogue (not updates)
- All console output uses `rich.console.Console` — no bare `print()`
- LLM calls retry up to 3 times on JSON parse failure, feeding the error back
