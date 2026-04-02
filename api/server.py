from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import config


# ── Audit log helper ───────────────────────────────────────────────────────────

def append_audit(
    session: dict,
    phase: int,
    event_type: str,
    title: str,
    detail: str,
    data: dict | None = None,
    status: str = "info",
) -> None:
    try:
        session["audit_log"].append({
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "event_type": event_type,
            "title": title,
            "detail": detail,
            "data": data,
            "status": status,
        })
    except Exception:
        pass


# ── Session store ──────────────────────────────────────────────────────────────

sessions: dict[str, dict] = {}


def new_session() -> dict:
    return {
        "db": {
            "type": "postgresql",
            "host": "localhost",
            "port": 5432,
            "database": "",
            "username": "",
            "password": "",
        },
        "superset": {
            "url": config.SUPERSET_URL,
            "username": config.SUPERSET_USERNAME,
            "password": config.SUPERSET_PASSWORD,
        },
        "llm_model": config.LLM_MODEL,
        "db_connector": None,
        "phase1": {
            "schema_map": None,
            "confirmed": False,
            "business_prompt": "",
            "cache_key": None,
            "excluded_tables": {},
        },
        "phase2": {
            "query_plan": None,
            "qa_report": None,
            "confirmed": False,
            "edited_sql": "",
        },
        "phase3": {
            "dataset_name": "",
            "dashboard_title": "",
            "requirements": "",
            "dataset_info": None,
            "parsed_reqs": None,
            "dashboard_plan": None,
            "plan_ready": False,
            "dashboard_url": None,
        },
        "audit_log": [],
    }


def get_session(sid: str) -> dict:
    if sid not in sessions:
        raise HTTPException(status_code=404, detail=f"Session '{sid}' not found")
    return sessions[sid]


def serialize_session(sess: dict) -> dict:
    """Return a JSON-serializable snapshot (no live objects)."""
    result = {}
    for key, val in sess.items():
        if key == "db_connector":
            result[key] = None
            continue
        if isinstance(val, dict):
            inner = {}
            for k, v in val.items():
                if hasattr(v, "model_dump"):
                    inner[k] = v.model_dump()
                elif isinstance(v, dict):
                    nested = {}
                    for nk, nv in v.items():
                        if hasattr(nv, "model_dump"):
                            nested[nk] = nv.model_dump()
                        else:
                            nested[nk] = nv
                    inner[k] = nested
                else:
                    inner[k] = v
            result[key] = inner
        else:
            result[key] = val
    return result


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(title="Superset Dashboard Builder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────

class DbConfig(BaseModel):
    type: str = "postgresql"
    host: str = "localhost"
    port: int = 5432
    database: str = ""
    username: str = ""
    password: str = ""


class SupersetConfig(BaseModel):
    url: str = "http://localhost:8088"
    username: str = "admin"
    password: str = ""


class SessionConfigUpdate(BaseModel):
    db: DbConfig | None = None
    superset: SupersetConfig | None = None
    llm_model: str | None = None


class ProfileTableBody(BaseModel):
    table_name: str


class AddTableBody(BaseModel):
    table_name: str
    selected_columns: list[str]


class ConfirmPhase2Body(BaseModel):
    edited_sql: str


# ── Session endpoints ─────────────────────────────────────────────────────────

@app.post("/api/session")
async def create_session():
    sid = str(uuid.uuid4())
    sessions[sid] = new_session()
    return {"session_id": sid}


@app.get("/api/config/defaults")
async def get_defaults():
    return {
        "superset_url": config.SUPERSET_URL,
        "superset_username": config.SUPERSET_USERNAME,
        "llm_model": config.LLM_MODEL,
    }


@app.get("/api/sessions/{sid}/state")
async def get_state(sid: str):
    sess = get_session(sid)
    return serialize_session(sess)


@app.put("/api/sessions/{sid}/config")
async def update_config(sid: str, body: SessionConfigUpdate):
    sess = get_session(sid)
    if body.db is not None:
        sess["db"] = body.db.model_dump()
        # Reset connector when config changes
        sess["db_connector"] = None
    if body.superset is not None:
        sess["superset"] = body.superset.model_dump()
    if body.llm_model is not None:
        sess["llm_model"] = body.llm_model
    return {"ok": True}


@app.post("/api/sessions/{sid}/db/test")
async def test_db_connection(sid: str):
    sess = get_session(sid)
    db = sess["db"]
    try:
        from tools.db_connector import DBConnector
        connector = DBConnector(
            db_type=db["type"],
            host=db["host"],
            port=int(db["port"]),
            database=db["database"],
            username=db["username"],
            password=db["password"],
        )
        ok, message = connector.test_connection()
        if ok:
            sess["db_connector"] = connector
        return {"ok": ok, "message": message}
    except Exception as e:
        return {"ok": False, "message": str(e)}


# ── Phase 1 endpoints ─────────────────────────────────────────────────────────

@app.get("/api/sessions/{sid}/phase1/explore")
async def phase1_explore(sid: str, prompt: str = Query(...)):
    sess = get_session(sid)
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def worker():
        try:
            if sess.get("llm_model"):
                config.LLM_MODEL = sess["llm_model"]

            db_connector = sess.get("db_connector")
            if db_connector is None:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "error", "message": "No database connection. Test connection first."},
                )
                return

            append_audit(sess, 1, "prompt_entered", "Prompt entered", prompt, status="info")

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Getting all tables from database...", "step": 1, "total": 3},
            )

            from agents.schema_explorer import SchemaExplorer
            explorer = SchemaExplorer()
            profiled_tables = explorer.run(prompt, db_connector)

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": f"Profiled {len(profiled_tables)} tables. Analyzing context...", "step": 2, "total": 3},
            )

            from agents.context_analyst import ContextAnalyst
            analyst = ContextAnalyst()
            schema_map = analyst.run(prompt, profiled_tables)

            append_audit(
                sess, 1, "tables_discovered", "Tables discovered",
                f"Found {len(schema_map.all_tables)} tables in database",
                data={"all_tables": schema_map.all_tables, "count": len(schema_map.all_tables)},
                status="info",
            )

            selected_names_set = {t.table_name for t in schema_map.profiled_tables}
            append_audit(
                sess, 1, "tables_selected",
                f"Agent selected {len(schema_map.profiled_tables)} tables",
                schema_map.agent_reasoning,
                data={
                    "selected": [t.table_name for t in schema_map.profiled_tables],
                    "excluded": [t for t in schema_map.all_tables if t not in selected_names_set],
                    "suggested_primary": schema_map.suggested_primary,
                    "suggested_joins": schema_map.suggested_joins,
                },
                status="success",
            )

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Profiling excluded tables...", "step": 3, "total": 3},
            )

            # Profile excluded tables
            selected_names = {t.table_name for t in schema_map.profiled_tables}
            all_tables = schema_map.all_tables
            excluded_tables: dict[str, Any] = {}

            for tname in all_tables:
                if tname not in selected_names:
                    try:
                        profile = db_connector.profile_table(tname)
                        excluded_tables[tname] = {
                            "profiled": True,
                            "profile": profile.model_dump(),
                            "selected_columns": [],
                            "added": False,
                            "error": None,
                        }
                    except Exception as e:
                        excluded_tables[tname] = {
                            "profiled": False,
                            "profile": None,
                            "selected_columns": [],
                            "added": False,
                            "error": str(e),
                        }

            sess["phase1"]["schema_map"] = schema_map
            sess["phase1"]["business_prompt"] = prompt
            sess["phase1"]["excluded_tables"] = excluded_tables
            sess["phase1"]["confirmed"] = False

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "done",
                    "data": {
                        "schema_map": schema_map.model_dump(),
                        "excluded_tables": excluded_tables,
                    },
                },
            )
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": str(e)},
            )

    loop.run_in_executor(None, worker)

    async def generate() -> AsyncGenerator[str, None]:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=300)
            except asyncio.TimeoutError:
                yield sse({"type": "error", "message": "Timeout waiting for agent response"})
                break
            yield sse(item)
            if item["type"] in ("done", "error"):
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/sessions/{sid}/phase1/profile-table")
async def phase1_profile_table(sid: str, body: ProfileTableBody):
    sess = get_session(sid)
    db_connector = sess.get("db_connector")
    if db_connector is None:
        raise HTTPException(status_code=400, detail="No database connection")
    try:
        profile = db_connector.profile_table(body.table_name)
        excluded = sess["phase1"]["excluded_tables"]
        if body.table_name not in excluded:
            excluded[body.table_name] = {
                "profiled": False,
                "profile": None,
                "selected_columns": [],
                "added": False,
                "error": None,
            }
        excluded[body.table_name]["profiled"] = True
        excluded[body.table_name]["profile"] = profile.model_dump()
        excluded[body.table_name]["error"] = None
        return profile.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sessions/{sid}/phase1/add-table")
async def phase1_add_table(sid: str, body: AddTableBody):
    sess = get_session(sid)
    excluded = sess["phase1"]["excluded_tables"]
    schema_map = sess["phase1"].get("schema_map")
    if schema_map is None:
        raise HTTPException(status_code=400, detail="No schema map. Run explore first.")

    entry = excluded.get(body.table_name)
    if entry is None or not entry.get("profiled") or entry.get("profile") is None:
        raise HTTPException(status_code=400, detail="Table not profiled yet")

    from models.schemas import ColumnProfile, TableProfile

    raw_profile = entry["profile"]
    all_cols = raw_profile.get("columns", [])
    if body.selected_columns:
        filtered_cols = [c for c in all_cols if c["column_name"] in body.selected_columns]
    else:
        filtered_cols = all_cols

    tp = TableProfile(
        table_name=raw_profile["table_name"],
        row_count=raw_profile["row_count"],
        columns=[ColumnProfile(**c) for c in filtered_cols],
        sample_rows=raw_profile.get("sample_rows", []),
    )

    existing_names = {t.table_name for t in schema_map.profiled_tables}
    if tp.table_name not in existing_names:
        schema_map.profiled_tables.append(tp)
        if tp.table_name not in schema_map.all_tables:
            schema_map.all_tables.append(tp.table_name)

    excluded[body.table_name]["added"] = True
    excluded[body.table_name]["selected_columns"] = body.selected_columns

    col_list = ", ".join(body.selected_columns) if body.selected_columns else "all columns"
    append_audit(
        sess, 1, "table_manually_added",
        f"User added table: {body.table_name}",
        f"Columns selected: {col_list}",
        data={"table_name": body.table_name, "columns": body.selected_columns},
        status="info",
    )

    return {"ok": True}


@app.post("/api/sessions/{sid}/phase1/confirm")
async def phase1_confirm(sid: str):
    sess = get_session(sid)
    if sess["phase1"].get("schema_map") is None:
        raise HTTPException(status_code=400, detail="No schema map to confirm")
    sess["phase1"]["confirmed"] = True
    schema_map = sess["phase1"]["schema_map"]
    n = len(schema_map.profiled_tables) if hasattr(schema_map, "profiled_tables") else 0
    append_audit(
        sess, 1, "phase1_confirmed", "Schema confirmed",
        f"Proceeding with {n} tables",
        status="success",
    )
    return {"ok": True}


# ── Phase 2 endpoints ─────────────────────────────────────────────────────────

@app.get("/api/sessions/{sid}/phase2/generate")
async def phase2_generate(sid: str):
    sess = get_session(sid)
    if not sess["phase1"].get("confirmed"):
        raise HTTPException(status_code=400, detail="Phase 1 not confirmed")

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def worker():
        try:
            if sess.get("llm_model"):
                config.LLM_MODEL = sess["llm_model"]

            schema_map = sess["phase1"].get("schema_map")
            db_connector = sess.get("db_connector")
            business_prompt = sess["phase1"].get("business_prompt", "")

            if schema_map is None:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "error", "message": "No schema map found"},
                )
                return

            MAX_RETRIES = 2
            last_error = ""
            query_plan = None

            for attempt in range(MAX_RETRIES + 1):
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {
                        "type": "progress",
                        "message": f"Writing JOIN query{'(retry ' + str(attempt) + ')' if attempt > 0 else ''}...",
                        "step": 1,
                        "total": 2,
                    },
                )

                if attempt > 0 and last_error:
                    append_audit(
                        sess, 2, "query_retry", "Query retry triggered",
                        last_error,
                        data={"error": last_error, "attempt": attempt},
                        status="warning",
                    )

                from agents.query_architect import QueryArchitect
                architect = QueryArchitect()

                prompt_with_error = business_prompt
                if last_error:
                    prompt_with_error += f"\n\nPrevious SQL failed with error: {last_error}\nPlease fix the SQL."

                query_plan = architect.run(prompt_with_error, schema_map)

                append_audit(
                    sess, 2, "query_generated",
                    f"Query generated (attempt {attempt + 1})",
                    query_plan.grain_description or "Query generated",
                    data={
                        "attempt": attempt + 1,
                        "sql_preview": query_plan.sql[:200] + ("..." if len(query_plan.sql) > 200 else ""),
                        "calculated_columns": [c["name"] if isinstance(c, dict) else c.name for c in query_plan.calculated_columns],
                    },
                    status="info",
                )

                if db_connector is None:
                    break

                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "progress", "message": "Running QA checks against database...", "step": 2, "total": 2},
                )

                from agents.dataset_qa import DatasetQA
                qa_agent = DatasetQA()
                qa_report = qa_agent.run(query_plan, db_connector)

                append_audit(
                    sess, 2, "qa_result",
                    f"QA {'passed' if qa_report.passed else 'failed'}",
                    "; ".join(qa_report.issues) if qa_report.issues else "No issues found",
                    data={
                        "passed": qa_report.passed,
                        "row_count": qa_report.row_count,
                        "duplicate_count": qa_report.duplicate_row_count,
                        "issues": qa_report.issues,
                        "suggestions": qa_report.suggestions,
                    },
                    status="success" if qa_report.passed else "error",
                )

                sess["phase2"]["query_plan"] = query_plan
                sess["phase2"]["qa_report"] = qa_report
                sess["phase2"]["edited_sql"] = query_plan.sql
                sess["phase2"]["confirmed"] = False

                if qa_report.passed or attempt >= MAX_RETRIES:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {
                            "type": "done",
                            "data": {
                                "query_plan": query_plan.model_dump(),
                                "qa_report": qa_report.model_dump(),
                            },
                        },
                    )
                    return
                else:
                    sql_errors = [i for i in qa_report.issues if "execution failed" in i.lower() or "syntax" in i.lower()]
                    if sql_errors:
                        last_error = "; ".join(sql_errors)
                    else:
                        # Non-SQL QA issues (duplicates, fan-out) — send done with current results
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            {
                                "type": "done",
                                "data": {
                                    "query_plan": query_plan.model_dump(),
                                    "qa_report": qa_report.model_dump(),
                                },
                            },
                        )
                        return

            # No db_connector path
            if query_plan is not None and db_connector is None:
                sess["phase2"]["query_plan"] = query_plan
                sess["phase2"]["edited_sql"] = query_plan.sql
                sess["phase2"]["confirmed"] = False
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {
                        "type": "done",
                        "data": {
                            "query_plan": query_plan.model_dump(),
                            "qa_report": None,
                        },
                    },
                )

        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": str(e)},
            )

    loop.run_in_executor(None, worker)

    async def generate() -> AsyncGenerator[str, None]:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=300)
            except asyncio.TimeoutError:
                yield sse({"type": "error", "message": "Timeout"})
                break
            yield sse(item)
            if item["type"] in ("done", "error"):
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/sessions/{sid}/phase2/confirm")
async def phase2_confirm(sid: str, body: ConfirmPhase2Body):
    sess = get_session(sid)
    if sess["phase2"].get("query_plan") is None:
        raise HTTPException(status_code=400, detail="No query plan to confirm")
    sess["phase2"]["confirmed"] = True
    sess["phase2"]["edited_sql"] = body.edited_sql
    # Pre-fill phase3 dataset name
    qp = sess["phase2"]["query_plan"]
    dataset_name = ""
    if qp and hasattr(qp, "dataset_name_suggestion"):
        dataset_name = qp.dataset_name_suggestion
        sess["phase3"]["dataset_name"] = dataset_name
    append_audit(
        sess, 2, "phase2_confirmed", "Query confirmed",
        f"Dataset name: {dataset_name}",
        data={"dataset_name_suggestion": dataset_name},
        status="success",
    )
    return {"ok": True}


# ── Phase 3 endpoints ─────────────────────────────────────────────────────────

@app.get("/api/sessions/{sid}/phase3/plan")
async def phase3_plan(
    sid: str,
    dataset_name: str = Query(...),
    dashboard_title: str = Query(...),
    requirements: str = Query(...),
):
    sess = get_session(sid)
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def worker():
        try:
            if sess.get("llm_model"):
                config.LLM_MODEL = sess["llm_model"]

            superset_cfg = sess["superset"]

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Authenticating with Superset...", "step": 1, "total": 5},
            )
            from tools.superset_api import SupersetClient
            client = SupersetClient(
                base_url=superset_cfg["url"] or config.SUPERSET_URL,
                username=superset_cfg["username"] or config.SUPERSET_USERNAME,
                password=superset_cfg["password"] or config.SUPERSET_PASSWORD,
            )
            client.authenticate()

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Fetching dataset info...", "step": 2, "total": 5},
            )
            dataset_info = client.get_dataset_by_name(dataset_name)

            append_audit(
                sess, 3, "dataset_loaded",
                f"Dataset loaded: {dataset_info.name}",
                f"{len(dataset_info.columns)} columns",
                data={"dataset_name": dataset_info.name, "column_count": len(dataset_info.columns)},
                status="info",
            )

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Sampling column values...", "step": 3, "total": 5},
            )
            from tools.column_sampler import ColumnSampler
            sampler = ColumnSampler(client)
            dataset_info = sampler.enrich_columns(dataset_info)

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Parsing requirements...", "step": 4, "total": 5},
            )
            from agents.requirements_parser import RequirementsParser
            parser = RequirementsParser()
            parsed_reqs = parser.run(requirements, dataset_info)

            flagged = parsed_reqs.get("flagged", []) if isinstance(parsed_reqs, dict) else []
            charts_list = parsed_reqs.get("charts", []) if isinstance(parsed_reqs, dict) else []
            req_detail = f"{len(charts_list)} chart intents extracted"
            if flagged:
                req_detail += f", {len(flagged)} flagged"
            append_audit(
                sess, 3, "requirements_parsed", "Requirements parsed",
                req_detail,
                data={
                    "chart_count": len(charts_list),
                    "flagged": flagged,
                    "chart_intents": [c.get("intent", "") for c in charts_list if isinstance(c, dict)],
                },
                status="warning" if flagged else "success",
            )

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Planning charts...", "step": 5, "total": 5},
            )
            from agents.chart_strategist import ChartStrategist
            from tools.catalogue import CatalogueManager
            catalogue = CatalogueManager()
            strategist = ChartStrategist()
            dashboard_plan = strategist.run(parsed_reqs, dataset_info, catalogue, dashboard_title)

            plan_detail = ", ".join(
                f"{c.viz_type}: {c.title}" for c in dashboard_plan.charts
            )
            append_audit(
                sess, 3, "dashboard_planned",
                f"Dashboard planned: {len(dashboard_plan.charts)} charts",
                plan_detail,
                data={
                    "charts": [
                        {"title": c.title, "viz_type": c.viz_type,
                         "reasoning": c.reasoning, "width": c.width}
                        for c in dashboard_plan.charts
                    ],
                    "filters": [f.column_name for f in dashboard_plan.filters],
                },
                status="success",
            )

            sess["phase3"]["dataset_name"] = dataset_name
            sess["phase3"]["dashboard_title"] = dashboard_title
            sess["phase3"]["requirements"] = requirements
            sess["phase3"]["dataset_info"] = dataset_info
            sess["phase3"]["parsed_reqs"] = parsed_reqs
            sess["phase3"]["dashboard_plan"] = dashboard_plan
            sess["phase3"]["plan_ready"] = True

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "done",
                    "data": {
                        "dataset_info": dataset_info.model_dump(),
                        "parsed_reqs": parsed_reqs,
                        "dashboard_plan": dashboard_plan.model_dump(),
                    },
                },
            )
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": str(e)},
            )

    loop.run_in_executor(None, worker)

    async def generate() -> AsyncGenerator[str, None]:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=300)
            except asyncio.TimeoutError:
                yield sse({"type": "error", "message": "Timeout"})
                break
            yield sse(item)
            if item["type"] in ("done", "error"):
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/sessions/{sid}/phase3/build")
async def phase3_build(
    sid: str,
    dashboard_id: str | None = Query(default=None),
    dry_run: bool = Query(default=False),
):
    sess = get_session(sid)
    if not sess["phase3"].get("plan_ready"):
        raise HTTPException(status_code=400, detail="No dashboard plan. Run plan first.")

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def worker():
        try:
            if sess.get("llm_model"):
                config.LLM_MODEL = sess["llm_model"]

            if dry_run:
                plan = sess["phase3"]["dashboard_plan"]
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {
                        "type": "done",
                        "data": {
                            "dry_run": True,
                            "dashboard_plan": plan.model_dump() if hasattr(plan, "model_dump") else plan,
                            "dashboard_url": None,
                            "qa_report": None,
                            "chart_actions": [],
                        },
                    },
                )
                return

            superset_cfg = sess["superset"]
            dataset_info = sess["phase3"]["dataset_info"]
            dashboard_plan = sess["phase3"]["dashboard_plan"]

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Authenticating with Superset...", "step": 1, "total": 7},
            )
            from tools.superset_api import SupersetClient, build_position_json
            client = SupersetClient(
                base_url=superset_cfg["url"] or config.SUPERSET_URL,
                username=superset_cfg["username"] or config.SUPERSET_USERNAME,
                password=superset_cfg["password"] or config.SUPERSET_PASSWORD,
            )
            client.authenticate()

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Fetching existing charts...", "step": 2, "total": 7},
            )
            existing_charts = client.get_charts_for_dataset(dataset_info.id)

            chart_ids: list[int] = []
            chart_actions: list[tuple[int, str]] = []
            total_charts = len(dashboard_plan.charts)

            for i, chart_spec in enumerate(dashboard_plan.charts):
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {
                        "type": "progress",
                        "message": f"Creating chart {i + 1}/{total_charts}: {chart_spec.title}...",
                        "step": 3,
                        "total": 7,
                    },
                )
                chart_id, action = client.upsert_chart(dataset_info.id, chart_spec, existing_charts)
                chart_ids.append(chart_id)
                chart_actions.append((chart_id, action))
                append_audit(
                    sess, 3, "chart_created",
                    f"Chart created: {chart_spec.title}",
                    f"{chart_spec.viz_type} · {action}",
                    data={"chart_id": chart_id, "action": action},
                    status="success",
                )

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Building dashboard layout...", "step": 4, "total": 7},
            )
            position_json = build_position_json(chart_ids, dashboard_plan.charts)

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Creating/Updating dashboard...", "step": 5, "total": 7},
            )

            try:
                did = int(dashboard_id) if dashboard_id else None
            except ValueError:
                raise ValueError(f"Invalid dashboard ID '{dashboard_id}' — must be a number")
            if did:
                dashboard_url = client.update_dashboard(did, chart_ids, position_json)
                dash_action = "updated"
            else:
                did, dashboard_url = client.create_dashboard(
                    dashboard_plan.dashboard_title, chart_ids, position_json
                )
                dash_action = "created"

            append_audit(
                sess, 3, "dashboard_created",
                f"Dashboard {dash_action} in Superset",
                f"{len(chart_ids)} charts · {len(dashboard_plan.filters)} filters",
                data={
                    "dashboard_id": did,
                    "dashboard_url": dashboard_url,
                    "chart_count": len(chart_ids),
                    "filter_count": len(dashboard_plan.filters),
                },
                status="success",
            )

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Configuring filters...", "step": 6, "total": 7},
            )
            client.set_dashboard_filters(did, dashboard_plan.filters, dataset_info.id)

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "message": "Running QA review...", "step": 7, "total": 7},
            )
            from agents.qa_reviewer import QAReviewer
            qa = QAReviewer()
            qa_report = qa.run(dashboard_plan, dataset_info, chart_actions, client)

            append_audit(
                sess, 3, "qa_review",
                f"QA {'passed' if qa_report.passed else 'failed'}",
                "; ".join(qa_report.issues) if qa_report.issues else "All checks passed",
                data={"passed": qa_report.passed, "issues": qa_report.issues},
                status="success" if qa_report.passed else "warning",
            )

            append_audit(
                sess, 3, "dashboard_live",
                "Dashboard live",
                dashboard_url,
                data={"url": dashboard_url},
                status="success",
            )

            # Persist audit log to disk
            try:
                runs_dir = Path("runs")
                runs_dir.mkdir(exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                audit_file = runs_dir / f"audit_{ts}.json"
                with open(audit_file, "w") as _f:
                    json.dump(
                        {"session_id": sid, "created_at": ts, "entries": sess["audit_log"]},
                        _f,
                        indent=2,
                        default=str,
                    )
            except Exception:
                pass

            sess["phase3"]["dashboard_url"] = dashboard_url

            # Update catalogue
            try:
                from tools.catalogue import CatalogueManager
                from models.schemas import CatalogueEntry
                catalogue = CatalogueManager()
                new_entries = []
                for chart_spec, (chart_id, action) in zip(dashboard_plan.charts, chart_actions):
                    if action == "created":
                        entry = CatalogueEntry(
                            client_hint=sess["phase3"].get("dashboard_title", ""),
                            intent=chart_spec.title,
                            viz_type=chart_spec.viz_type,
                            metric_columns=[
                                (m.get("column") or {}).get("column_name", "")
                                for m in chart_spec.metrics
                                if m.get("expressionType") == "SIMPLE"
                            ],
                            dimension_columns=chart_spec.groupby,
                            time_column=chart_spec.time_column,
                            worked_well=qa_report.passed,
                            notes="; ".join(qa_report.suggestions[:2]),
                        )
                        new_entries.append(entry)
                if new_entries:
                    catalogue.append(new_entries)
            except Exception:
                pass

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "done",
                    "data": {
                        "dashboard_url": dashboard_url,
                        "qa_report": qa_report.model_dump(),
                        "chart_actions": [
                            {"chart_id": cid, "action": act} for cid, act in chart_actions
                        ],
                    },
                },
            )
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": str(e)},
            )

    loop.run_in_executor(None, worker)

    async def generate() -> AsyncGenerator[str, None]:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=300)
            except asyncio.TimeoutError:
                yield sse({"type": "error", "message": "Timeout"})
                break
            yield sse(item)
            if item["type"] in ("done", "error"):
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Audit log endpoints ───────────────────────────────────────────────────────

@app.get("/api/sessions/{sid}/audit")
async def get_audit_log(sid: str):
    sess = get_session(sid)
    return {"entries": sess.get("audit_log", [])}


@app.delete("/api/sessions/{sid}/audit")
async def clear_audit_log(sid: str):
    sess = get_session(sid)
    sess["audit_log"] = []
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
