# Superset Dashboard Builder — Project Context

## What This Project Does

A three-phase tool for end-to-end Superset dashboard creation:

- **Phase 1** — Schema explorer: connects to a live database, profiles tables, uses LLM to identify relevant tables and suggest joins
- **Phase 2** — Query builder: generates a master JOIN SQL query, adds calculated columns, runs QA checks against the live DB
- **Phase 3** — Dashboard builder: takes an existing Superset dataset, uses LLM to plan charts, creates them via REST API, assembles the dashboard, sets up filters, runs QA

**Interfaces:**
- `api/server.py` — FastAPI backend, exposes all agents as REST + SSE endpoints on `http://localhost:8000`
- `frontend/` — React 18 + TypeScript + Vite UI on `http://localhost:5173` *(primary UI)*
- `main.py` — CLI (typer), Phase 3 only, for scripted/automated use

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
├── main.py                    # CLI entrypoint (typer), Phase 3 only, 13-step orchestrator
├── config.py                  # Loads .env into a Config singleton
├── api/
│   ├── __init__.py
│   └── server.py              # FastAPI backend — REST + SSE endpoints, runs at :8000
├── frontend/                  # React 18 + TypeScript + Vite UI, runs at :5173
│   ├── src/
│   │   ├── App.tsx            # Root: session init, theme sync to <html>, layout
│   │   ├── main.tsx           # React 18 entry, mounts <App> + <Toaster>
│   │   ├── index.css          # Tailwind + CSS variables for light/dark theme
│   │   ├── types/index.ts     # TypeScript types mirroring all Pydantic models
│   │   ├── store/appStore.ts  # Zustand store (persisted: sessionId, theme, configs)
│   │   ├── api/client.ts      # Typed API client (fetch + EventSource helpers)
│   │   ├── hooks/useSSE.ts    # SSE streaming hook (logs, isStreaming, result, error)
│   │   └── components/
│   │       ├── layout/
│   │       │   ├── Header.tsx # Step indicator (Schema→Query→Dashboard) + theme toggle
│   │       │   └── Sidebar.tsx# Collapsible DB/Superset/LLM config, debounced server sync
│   │       ├── phases/
│   │       │   ├── Phase1.tsx # Schema Explorer UI
│   │       │   ├── Phase2.tsx # Query Builder UI (CodeMirror SQL editor)
│   │       │   └── Phase3.tsx # Dashboard Builder UI
│   │       └── ui/
│   │           ├── Badge.tsx, Button.tsx, Card.tsx
│   │           ├── DataTable.tsx, Input.tsx
│   │           ├── ProgressLog.tsx  # Terminal-style SSE log with spinner/checkmark
│   │           └── Spinner.tsx
│   ├── package.json           # React deps: zustand, framer-motion, lucide-react,
│   │                          #   @uiw/react-codemirror, @codemirror/lang-sql,
│   │                          #   @uiw/codemirror-theme-dracula, sonner, clsx
│   ├── vite.config.ts         # Vite: proxy /api → localhost:8000
│   ├── tailwind.config.js     # CSS-variable-driven colors (theme-aware)
│   └── tsconfig.json
├── agents/
│   ├── schema_explorer.py     # Phase 1 Agent 1: DB tables → list[TableProfile]
│   ├── context_analyst.py     # Phase 1 Agent 2: TableProfiles → SchemaMap
│   ├── query_architect.py     # Phase 2 Agent 1: SchemaMap → QueryPlan (2 LLM passes)
│   ├── dataset_qa.py          # Phase 2 Agent 2: QueryPlan + DB → DatasetQAReport
│   ├── requirements_parser.py # Phase 3 Agent 1: requirements → grounded JSON
│   ├── chart_strategist.py    # Phase 3 Agent 2: chart intents → DashboardPlan
│   └── qa_reviewer.py         # Phase 3 Agent 3: rule-based + LLM QA → QAReport
├── tools/
│   ├── db_connector.py        # DBConnector: PostgreSQL/MySQL (SQLAlchemy) + MongoDB (pymongo)
│   ├── superset_api.py        # SupersetClient, build_position_json, build_chart_params
│   ├── column_sampler.py      # Samples distinct values for low-cardinality string cols
│   ├── catalogue.py           # Manages charts_catalogue.json across runs
│   ├── llm_client.py          # Shared LiteLLM/OpenAI-compatible client — used by all agents
│   └── notifier.py            # Slack webhook + SMTP email (both optional)
├── models/
│   └── schemas.py             # All Pydantic v2 models (Phase 1+2+3)
├── runs/                      # One JSON state file per run (for resume)
├── previews/                  # Markdown dashboard previews
├── charts_catalogue.json      # Grows over time; stores successful chart specs
├── .env.example               # Template — copy to .env and fill in
└── requirements.txt           # Added: fastapi, uvicorn[standard], sse-starlette
```

---

## Pydantic Models (models/schemas.py)

### Phase 3 models (existing)

| Model | Purpose |
|-------|---------|
| `DatasetColumn` | One column: name, type, is_dttm, expression, distinct_values |
| `DatasetInfo` | Full dataset: id, name, columns list, metrics list |
| `FilterSpec` | One native filter: column, filter_type, default_value, label |
| `ChartSpec` | One chart: title, viz_type, metrics, groupby, time fields, width, reasoning |
| `DashboardPlan` | Full plan: title, charts list, filters list, position_json, reasoning |
| `QAReport` | QA result: passed bool, issues list, suggestions list |
| `CatalogueEntry` | Catalogue record: client_hint, intent, viz_type, columns, worked_well, notes |

### Phase 1 & 2 models (new)

| Model | Purpose |
|-------|---------|
| `ColumnProfile` | One column from a live DB table: name, type, sample_values, null_pct, flag booleans |
| `TableProfile` | One DB table: name, row_count, columns list, sample_rows |
| `SchemaMap` | Output of Phase 1: all_tables, profiled_tables, suggested_primary, suggested_joins, reasoning |
| `QueryPlan` | Output of Phase 2 Agent 1: sql, calculated_columns, dataset_name_suggestion, grain_description |
| `DatasetQAReport` | Output of Phase 2 Agent 2: passed, row_count, dup_count, issues, suggestions, sample_rows |

---

## Tools

### tools/db_connector.py

`DBConnector(db_type, host, port, database, username, password)`
- `db_type`: `"postgresql"`, `"mysql"`, `"mongodb"`
- Connection is lazy — nothing happens in `__init__`
- PostgreSQL/MySQL: SQLAlchemy (`psycopg2` / `pymysql` drivers)
- MongoDB: `pymongo`

Key methods — **all return tuples, never raise**:
- `test_connection()` → `(bool, str)`
- `get_all_tables()` → `list[str]`
- `profile_table(name)` → `TableProfile`
- `run_query(sql, limit)` → `(bool, list[dict], str)`
- `get_row_count(sql)` → `(bool, int, str)`
- `check_duplicates(sql)` → `(bool, int, str)` — compares COUNT(*) vs COUNT(DISTINCT *)

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
- `set_dashboard_filters(id, filters, dataset_id)` — PUT `json_metadata` with native filter config

**`build_position_json(chart_ids, chart_specs)`** — packs charts into 12-col rows using each
chart's `width` (3/6/12). Returns valid Superset v2 `position_json` tree.

**`VIZ_TYPE_MAP`**: `"bar" → "dist_bar"`, `"scatter" → "echarts_scatter"`

**`FORCED_WIDTHS`**: `big_number_total→3`, `echarts_timeseries_line→12`, `table→12`, `echarts_scatter→12`

### tools/column_sampler.py

`ColumnSampler.enrich_columns(dataset_info)`:
- For each STRING column: runs `SELECT DISTINCT col LIMIT 21` via `/api/v1/sqllab/execute/`
- ≤20 results → stores in `column.distinct_values`; 21 → high cardinality, leaves as `None`
- Each column wrapped in try/except — never crashes the pipeline

### tools/catalogue.py

`CatalogueManager` reads/writes `charts_catalogue.json`:
- `find_similar(intent)` — keyword overlap scoring, returns top-N entries
- `build_context_string(entries)` — formats entries for injection into Agent 2 prompt
- Only charts with `action="created"` are appended (not updates)

---

## Agents

All agents use `tools/llm_client.py → chat(system, user)` (OpenAI SDK → LiteLLM proxy).
All follow the same retry pattern: parse JSON, on failure retry up to 3x feeding the error back.

### Phase 1 Agents

**`schema_explorer.py` — `SchemaExplorer.run(prompt, db_connector)`**
- Gets all tables from DB
- ≤15 tables: profiles all; >15 tables: LLM shortlists then profiles candidates
- Shortlisting rules (RULE 1–6): include keyword matches, highest row-count table, FK dimension tables; exclude only exact system table names/endings (_archive, _backup, _tmp, _temp, _bak, migrations, schema_versions, etc.); default to include (30-50% of tables, minimum 3); trace FK chains up to 2 levels
- All LLM calls use `temperature=0`
- Returns `list[TableProfile]`

**`context_analyst.py` — `ContextAnalyst.run(prompt, profiled_tables)`**
- Receives profiled tables, selects the relevant subset
- Tables sorted by row_count descending before LLM call (fact table appears first)
- All LLM calls use `temperature=0`
- CORE SELECTION PRINCIPLE: only include a table if it provides a column not available from already-selected tables; the main reason to add a dimension table is a label gap (fact has X_id, prompt needs X name)
- Do NOT include tables just because they have a FK to the fact table
- Post-processing hard rules:
  1. `suggested_primary` = highest row-count selected table (enforced, never a dimension)
  2. `MIN_TABLES = 2` — if LLM selects fewer, top tables by row_count are added to reach minimum
- No FK inference or chain tracing in post-processing — table selection is LLM-only
- Identifies primary fact table, suggests joins
- Returns `SchemaMap`

### Phase 2 Agents

**`query_architect.py` — `QueryArchitect.run(prompt, schema_map)`**
- Pass 1: writes base JOIN SQL query with CTEs where needed
- Pass 2: identifies calculated columns to add to SELECT
- Merges calc columns into SQL, builds snake_case dataset name suggestion
- Returns `QueryPlan`

**`dataset_qa.py` — `DatasetQA.run(query_plan, db_connector)`**
- Runs SQL against live DB (limit 500), checks row count, checks duplicates
- LLM structural review: fan-out, NULL handling, division by zero
- Returns `DatasetQAReport` — `passed=False` if duplicates found or fan-out detected

### Phase 3 Agents

Each agent has **both** a module-level function (used by `main.py` CLI) and a class wrapper with `.run()` (used by `app.py`).

**`requirements_parser.py`** — function: `parse_requirements(requirements, dataset_info, verbose)`
Class: `RequirementsParser().run(requirements, dataset_info)`
- Grounds every column reference to real column names, flags unsatisfiable requirements
- Output: `{charts: [...], filter_bar: [...], flagged: [...]}`

**`chart_strategist.py`** — function: `plan_dashboard(parsed_requirements, dataset_info, catalogue_context, dashboard_title, verbose)`
Class: `ChartStrategist().run(parsed_reqs, dataset_info, catalogue, dashboard_title="Dashboard")`
- Selects viz_type, builds metrics, assigns width; class wrapper handles catalogue lookup internally
- Output: `DashboardPlan`

**`qa_reviewer.py`** — function: `run_qa(dashboard_plan, dataset_info, chart_actions, superset_client, verbose)`
Class: `QAReviewer().run(dashboard_plan, dataset_info, chart_actions, superset_client=None)`
- Rule-based checks first, then LLM coverage check; `superset_client` optional in class wrapper
- Output: `QAReport`

---

## React Frontend + FastAPI Backend

### How to start

```bash
# 1. FastAPI backend (from project root)
python3 -m uvicorn api.server:app --reload --port 8000

# 2. React frontend
cd frontend && npm run dev          # dev server on :5173
# or: npm run build                 # production build → frontend/dist/
```

### FastAPI backend (`api/server.py`)

Sessions stored in-memory as `dict[str, dict]` keyed by UUID `session_id`.
The `session_id` is created on first load and persisted in browser localStorage.

**Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/session` | Create new session, returns `{session_id}` |
| GET | `/api/config/defaults` | Return `.env` defaults |
| PUT | `/api/sessions/{sid}/config` | Update db/superset/llm config in session |
| POST | `/api/sessions/{sid}/db/test` | Test DB connection, store `DBConnector` in session |
| GET | `/api/sessions/{sid}/phase1/explore` | **SSE**: SchemaExplorer → ContextAnalyst → profile excluded tables |
| POST | `/api/sessions/{sid}/phase1/profile-table` | Profile one excluded table |
| POST | `/api/sessions/{sid}/phase1/add-table` | Add excluded table + chosen columns to schema_map |
| POST | `/api/sessions/{sid}/phase1/confirm` | Set phase1.confirmed = True |
| GET | `/api/sessions/{sid}/phase2/generate` | **SSE**: QueryArchitect (auto-retry ×2) → DatasetQA |
| POST | `/api/sessions/{sid}/phase2/confirm` | Store edited SQL, set phase2.confirmed = True |
| GET | `/api/sessions/{sid}/phase3/plan` | **SSE**: Superset auth → dataset fetch → RequirementsParser → ChartStrategist |
| GET | `/api/sessions/{sid}/phase3/build` | **SSE**: upsert charts → layout → create/update dashboard → filters → QA |
| GET | `/api/sessions/{sid}/state` | Return serializable session snapshot (page-refresh recovery) |

**SSE event shape:**
```json
{"type": "progress", "message": "Writing JOIN query...", "step": 1, "total": 2}
{"type": "done",     "data": { ... }}
{"type": "error",    "message": "..."}
```

All SSE workers run in a `ThreadPoolExecutor` via `run_in_executor`; progress is
pushed via `asyncio.Queue` + `call_soon_threadsafe`.

### React frontend

**State management:** Zustand store (`store/appStore.ts`) with `persist` middleware.
Persisted keys: `sessionId`, `theme`, `dbConfig`, `supersetConfig`, `llmModel`.

**Theme system:**
- Two modes: `dark` (default) and `light`, toggled by Sun/Moon button in the header
- `tailwind.config.js` uses CSS variables (`var(--color-bg)` etc.) instead of hardcoded hex
- `index.css` defines `:root` (light) and `.dark` (dark) variable sets
- `App.tsx` adds/removes `.dark` class on `<html>` when `theme` changes
- CodeMirror SQL editor uses `dracula` theme in dark mode, `defaultLightThemeOption` in light mode
- All transitions are animated via `transition: background-color 0.2s ease`

**Streaming:** `hooks/useSSE.ts` wraps `EventSource`; returns `{logs, isStreaming, isDone, result, error}`.
`ProgressLog.tsx` renders the log as a terminal-style panel with animated spinner.

**Phase navigation:** Steps are clickable only when the prior phase is confirmed.
`framer-motion` `AnimatePresence` handles transitions between phases.


---

## Orchestrator (main.py) — Phase 3 CLI only

```bash
python3 main.py run \
  --requirements "..." \
  --dataset "dataset_name" \
  --dashboard-title "My Dashboard" \
  [--dashboard-id 42]        # triggers update mode
  [--dry-run]                # plan only, no API calls
  [--preview]                # save markdown to previews/
  [--yes]                    # skip confirmation
  [--resume-from run_id]     # resume failed run
  [--notify-slack]
  [--notify-email]
  [--verbose]                # print full LLM prompts
  [--model claude-haiku-4-5] # override LLM_MODEL
  [--client-tag "retail"]
```

13-step flow: setup → fetch dataset → fetch existing (update mode) → Agent 1 → Agent 2 → confirm → upsert charts → build layout → create/update dashboard → set filters → QA → update catalogue → notify → summary.

---

## Known Superset 5.x Gotchas (Already Handled)

1. **`bar` → `dist_bar`** and **`scatter` → `echarts_scatter`**: mapped in `VIZ_TYPE_MAP`
2. **`position_json` must be a JSON string**: passed as `json.dumps(position_json)` in PUT body
3. **`json_metadata` must be a JSON string**: same — `json.dumps({...})`
4. **Native filters silently ignored** if `filter_sets_configuration` and `default_filters` missing
5. **Rison filter URLs must be encoded**: all `?q=` params go through `urllib.parse.quote`
6. **`/api/v1/dataset/{id}/column/{col}/values` does not exist in v5**: sampler uses sqllab execute
7. **`dashboard_slices` ORM table not writable via REST**: fixed with `_sync_chart_ownership()` subprocess
8. **marshmallow must stay on 3.x**: pinned in requirements.txt

---

## .env Keys

```
LITELLM_API_KEY       # required — your LiteLLM proxy key
LITELLM_BASE_URL      # required — e.g. https://litellm.yourcompany.com
LLM_MODEL             # default: claude-haiku-4-5
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

## Implementation Rules

- All HTTP calls to Superset go through `SupersetClient._request()` — no raw httpx elsewhere
- All `DBConnector` methods return tuples — never raise
- `notifier.notify()` is entirely wrapped in try/except — never raises
- `column_sampler.enrich_columns()` wraps each column in try/except
- `build_position_json()` called by orchestrator after chart creation, never inside Agent 2
- Only `action="created"` charts are written to catalogue (not updates)
- All CLI console output uses `rich.console.Console` — no bare `print()`
- LLM calls retry up to 3 times on JSON parse failure, feeding the error back
- All Phase 1 LLM calls use `temperature=0` for deterministic table selection
- `chat()` in `llm_client.py` accepts optional `temperature` param; omit for API default (~1.0)
- FastAPI session state (in-memory dict) is the server-side store; Zustand (persisted to localStorage) is the client-side store
- Phase 2 SSE worker auto-retries QueryArchitect + DatasetQA up to `MAX_RETRIES=2` on SQL errors
- Tailwind colors must use CSS variable references (not hardcoded hex) to support theme switching
- `DBConnector` instances are stored directly in the session dict — never serialized or pickled
- SSE endpoints are GET-only; all mutable state changes use POST/PUT endpoints
