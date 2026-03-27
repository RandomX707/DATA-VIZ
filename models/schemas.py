from __future__ import annotations
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
