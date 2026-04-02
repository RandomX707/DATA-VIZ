from __future__ import annotations
from typing import Any
from pydantic import BaseModel


class DatasetColumn(BaseModel):
    column_name: str
    type: str  # "STRING", "NUMERIC", "DATETIME"
    is_dttm: bool
    expression: str | None = None
    distinct_values: list[str] | None = None


class DatasetInfo(BaseModel):
    id: int
    name: str
    columns: list[DatasetColumn]
    metrics: list[dict]


class FilterSpec(BaseModel):
    column_name: str
    filter_type: str  # "time", "categorical", "numerical"
    default_value: str | None = None
    label: str


class ChartSpec(BaseModel):
    title: str
    viz_type: str
    metrics: list[dict]
    groupby: list[str]
    time_column: str | None = None
    time_grain: str | None = None
    filters: list[dict]
    row_limit: int | None = None
    sort_by: list[dict] | None = None
    reasoning: str
    width: int  # 3, 6, or 12


class DashboardPlan(BaseModel):
    dashboard_title: str
    charts: list[ChartSpec]
    filters: list[FilterSpec]
    position_json: dict = {}
    reasoning: str


class QAReport(BaseModel):
    passed: bool
    issues: list[str]
    suggestions: list[str]


class CatalogueEntry(BaseModel):
    client_hint: str
    intent: str
    viz_type: str
    metric_columns: list[str]
    dimension_columns: list[str]
    time_column: str | None = None
    worked_well: bool
    notes: str


# ── Phase 1 & 2 models ────────────────────────────────────────────────────────

class ColumnProfile(BaseModel):
    column_name: str
    data_type: str
    sample_values: list[str]      # up to 5 sample values as strings
    null_pct: float
    is_likely_pk: bool
    is_likely_fk: bool
    is_likely_date: bool


class TableProfile(BaseModel):
    table_name: str
    row_count: int
    columns: list[ColumnProfile]
    sample_rows: list[dict[str, Any]]   # 3 sample rows as dicts


class SchemaMap(BaseModel):
    all_tables: list[str]
    profiled_tables: list[TableProfile]
    suggested_primary: str
    suggested_joins: list[str]
    agent_reasoning: str


class QueryPlan(BaseModel):
    sql: str
    calculated_columns: list[dict[str, Any]]
    dataset_name_suggestion: str
    grain_description: str
    agent_reasoning: str


class DatasetQAReport(BaseModel):
    passed: bool
    row_count: int
    duplicate_row_count: int
    issues: list[str]
    suggestions: list[str]
    sample_rows: list[dict[str, Any]]   # 5 sample rows from running the query
