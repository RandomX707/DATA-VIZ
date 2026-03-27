# Superset Dashboard Builder

A Python CLI tool that automatically builds Apache Superset dashboards from plain-text stakeholder requirements using an LLM.

You describe what you want. The tool plans the charts, creates them in Superset via REST API, assembles the dashboard, sets up native filters, runs QA, and returns the live URL.

---

## How It Works

```
Plain-text requirements + Dataset name
          ↓
    Agent 1 — Parses requirements, grounds to real column names
          ↓
    Agent 2 — Plans charts, selects viz types, assigns layout
          ↓
    Confirmation table → Approve or dry-run
          ↓
    Superset REST API — Creates charts, dashboard, filters
          ↓
    Agent 3 — QA review (column checks + LLM coverage check)
          ↓
    Live dashboard URL
```

---

## Demo

```bash
python3 main.py run \
  --requirements "Show total employee count as KPI, daily attendance trend,
                  breakdown by department and location, top 10 by working hours" \
  --dataset "hr_biometric_data" \
  --dashboard-title "HR Attendance Overview" \
  --yes
```

Output:
```
Step 1 — Fetching dataset schema...        Found dataset: hr_biometric_data (14 columns)
Step 3 — Parsing requirements (Agent 1)...
Step 4 — Planning dashboard (Agent 2)...   Found 3 similar past charts in catalogue

┌─────────────────────────┬──────────────────────────┬───────┬──────────────────┐
│ Title                   │ Viz type                 │ Width │ Columns used     │
├─────────────────────────┼──────────────────────────┼───────┼──────────────────┤
│ Total Unique Employees  │ big_number_total         │ 3     │ EmployeeID       │
│ Daily Attendance Count  │ echarts_timeseries_line  │ 12    │ EmployeeID, Date │
│ Attendance by Dept      │ bar                      │ 6     │ Organization     │
│ Top 10 by Working Hours │ table                    │ 12    │ PersonName       │
└─────────────────────────┴──────────────────────────┴───────┴──────────────────┘

Step 6 — Building charts...   4/4 ✓
Step 8 — Assembling dashboard... Created dashboard id=11
Step 9 — Configuring filter bar... 5 native filters configured
Step 10 — QA review... ✓ All checks passed

Dashboard : HR Attendance Overview
URL       : http://localhost:8088/superset/dashboard/11
Charts    : 4 created, 0 updated
Filters   : 5 native filters configured
Issues    : 0
```

---

## Features

- **Plain-text requirements** — describe charts in natural language, no JSON or config files
- **Column grounding** — Agent 1 maps every requirement to real column names; flags anything it can't satisfy
- **Smart column sampling** — automatically samples distinct values for categorical columns to inform filter defaults
- **Catalogue memory** — successful chart specs are saved and reused across future runs
- **Upsert logic** — re-running on the same dataset updates existing charts instead of creating duplicates
- **Resume support** — if a run fails mid-way, resume from the last completed step
- **Native filter bar** — automatically configures Superset's native filter bar
- **QA review** — rule-based + LLM check on column validity and requirement coverage
- **Dry run + preview** — see the plan before making any API calls
- **Notifications** — optional Slack webhook or email on completion
- **Multi-model** — works with any model via LiteLLM proxy

---

## Project Structure

```
superset_dashboard_builder/
├── main.py                    # CLI entrypoint — 13-step orchestrator
├── config.py                  # Loads .env settings
├── agents/
│   ├── requirements_parser.py # Agent 1: requirements → grounded chart intents
│   ├── chart_strategist.py    # Agent 2: chart intents → DashboardPlan
│   └── qa_reviewer.py         # Agent 3: QA checks → QAReport
├── tools/
│   ├── superset_api.py        # SupersetClient + layout builder
│   ├── column_sampler.py      # Samples distinct values for categorical columns
│   ├── llm_client.py          # Shared LiteLLM/OpenAI-compatible client
│   ├── catalogue.py           # Persistent chart catalogue
│   └── notifier.py            # Slack + email notifications
├── models/
│   └── schemas.py             # Pydantic v2 models
├── runs/                      # Per-run state files (for resume)
├── previews/                  # Markdown dashboard previews
├── .env.example
└── requirements.txt
```

---

## Setup

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Configure environment**
```bash
cp .env.example .env
```

Edit `.env`:
```
LITELLM_API_KEY=your-litellm-key
LITELLM_BASE_URL=https://your-litellm-proxy.com
LLM_MODEL=claude-haiku-4-5

SUPERSET_URL=http://localhost:8088
SUPERSET_USERNAME=admin
SUPERSET_PASSWORD=admin
```

**3. Make sure Superset is running** with `WTF_CSRF_ENABLED = False` in your Superset config (required for REST API writes on local installs).

---

## Usage

### List available models
```bash
python3 main.py models
```

### Build a dashboard
```bash
python3 main.py run \
  --requirements "..." \
  --dataset "your_dataset_name" \
  --dashboard-title "My Dashboard"
```

### Dry run (no API calls — just see the plan)
```bash
python3 main.py run \
  --requirements "..." \
  --dataset "your_dataset_name" \
  --dashboard-title "My Dashboard" \
  --dry-run --preview
```

### Update an existing dashboard
```bash
python3 main.py run \
  --requirements "..." \
  --dataset "your_dataset_name" \
  --dashboard-title "My Dashboard" \
  --dashboard-id 42
```

### Resume a failed run
```bash
python3 main.py run \
  --requirements "..." \
  --dataset "your_dataset_name" \
  --dashboard-title "My Dashboard" \
  --resume-from run_20240315_143022
```

### All options
```
--requirements TEXT       Inline requirements string
--requirements-file PATH  Read requirements from a file
--dataset TEXT            Superset dataset name (required)
--dashboard-title TEXT    Dashboard title (required)
--dashboard-id INTEGER    Existing dashboard ID — triggers update mode
--model TEXT              LLM model override (e.g. gpt-4o, claude-haiku-4-5)
--superset-url TEXT       Superset base URL
--superset-username TEXT  Superset username
--superset-password TEXT  Superset password
--dry-run                 Plan only, no API calls
--preview                 Save markdown preview to previews/
--yes / -y                Skip confirmation prompt
--resume-from TEXT        Resume a failed run by run ID
--notify-slack            Send Slack notification on completion
--notify-email            Send email notification on completion
--verbose                 Print full LLM prompts and responses
--client-tag TEXT         Tag for catalogue entries (e.g. retail, saas)
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LITELLM_API_KEY` | Yes | — | Your LiteLLM proxy API key |
| `LITELLM_BASE_URL` | Yes | — | LiteLLM proxy URL |
| `LLM_MODEL` | No | `claude-haiku-4-5` | Model name (any on your proxy) |
| `SUPERSET_URL` | No | `http://localhost:8088` | Superset instance URL |
| `SUPERSET_USERNAME` | No | `admin` | Superset username |
| `SUPERSET_PASSWORD` | No | `admin` | Superset password |
| `SLACK_WEBHOOK_URL` | No | — | Slack webhook for notifications |
| `NOTIFY_EMAIL_FROM` | No | — | Sender email address |
| `NOTIFY_EMAIL_TO` | No | — | Recipient email address |
| `NOTIFY_EMAIL_SMTP` | No | `smtp.gmail.com` | SMTP host |
| `NOTIFY_EMAIL_PASSWORD` | No | — | SMTP password / app password |

---

## Requirements

- Python 3.10+
- Apache Superset 5.x (running locally or remote)
- LiteLLM proxy with access to at least one LLM model

---

## Supported Chart Types

| Viz Type | Width | Best For |
|----------|-------|----------|
| `big_number_total` | 3 | KPI / headline numbers |
| `echarts_timeseries_line` | 12 | Trends over time |
| `bar` (`dist_bar`) | 6 or 12 | Rankings, comparisons |
| `pie` | 6 | Part-of-whole, ≤6 categories |
| `table` | 12 | Leaderboards, detailed data |
| `scatter` | 12 | Correlation between two metrics |
