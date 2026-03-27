from __future__ import annotations

import json
import subprocess
import sys
import urllib.parse
import uuid

import httpx

from models.schemas import ChartSpec, DatasetColumn, DatasetInfo, FilterSpec

# Map spec viz_type names to Superset 5.x internal names
VIZ_TYPE_MAP = {
    "bar": "dist_bar",
    "scatter": "echarts_scatter",
    "big_number_total": "big_number_total",
    "echarts_timeseries_line": "echarts_timeseries_line",
    "pie": "pie",
    "table": "table",
}

# Enforce width rules post-LLM to prevent row-packing breakage
FORCED_WIDTHS: dict[str, int] = {
    "big_number_total": 3,
    "echarts_timeseries_line": 12,
    "table": 12,
    "echarts_scatter": 12,
    "scatter": 12,
}


def build_chart_params(chart_spec: ChartSpec) -> dict:
    viz = VIZ_TYPE_MAP.get(chart_spec.viz_type, chart_spec.viz_type)

    def single_metric(metrics: list[dict]) -> dict:
        return metrics[0] if metrics else {}

    if viz == "big_number_total":
        return {
            "viz_type": viz,
            "metric": single_metric(chart_spec.metrics),
            "subheader": "",
            "time_range": "No filter",
            "y_axis_format": "SMART_NUMBER",
        }

    if viz == "echarts_timeseries_line":
        return {
            "viz_type": viz,
            "metrics": chart_spec.metrics,
            "groupby": chart_spec.groupby,
            "granularity_sqla": chart_spec.time_column,
            "time_grain_sqla": chart_spec.time_grain or "P1M",
            "time_range": "No filter",
            "rich_tooltip": True,
            "show_legend": True,
        }

    if viz == "dist_bar":
        return {
            "viz_type": viz,
            "metrics": chart_spec.metrics,
            "groupby": chart_spec.groupby,
            "time_range": "No filter",
            "row_limit": chart_spec.row_limit or 50,
            "order_desc": True,
            "show_legend": False,
        }

    if viz == "table":
        return {
            "viz_type": viz,
            "metrics": chart_spec.metrics,
            "groupby": chart_spec.groupby,
            "time_range": "No filter",
            "row_limit": chart_spec.row_limit or 100,
            "order_desc": True,
            "table_timestamp_format": "smart_date",
        }

    if viz == "pie":
        return {
            "viz_type": viz,
            "metric": single_metric(chart_spec.metrics),
            "groupby": chart_spec.groupby,
            "time_range": "No filter",
            "row_limit": chart_spec.row_limit or 10,
            "donut": False,
            "show_legend": True,
            "show_labels": True,
        }

    if viz == "echarts_scatter":
        metrics = chart_spec.metrics
        return {
            "viz_type": viz,
            "metrics": metrics[:1],
            "x_axis": metrics[1]["column"]["column_name"] if len(metrics) > 1 else None,
            "groupby": chart_spec.groupby,
            "time_range": "No filter",
        }

    # Fallback for any unrecognised viz type
    return {
        "viz_type": viz,
        "metrics": chart_spec.metrics,
        "groupby": chart_spec.groupby,
        "time_range": "No filter",
    }


def build_position_json(chart_ids: list[int], chart_specs: list[ChartSpec]) -> dict:
    """
    Pack charts into 12-column rows and return a valid Superset v2 position_json.
    """
    position: dict = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": [],
            "parents": ["ROOT_ID"],
        },
    }

    rows: list[list[tuple[int, ChartSpec]]] = []
    current_row: list[tuple[int, ChartSpec]] = []
    remaining = 12

    for chart_id, spec in zip(chart_ids, chart_specs):
        # Enforce width rules
        width = FORCED_WIDTHS.get(
            VIZ_TYPE_MAP.get(spec.viz_type, spec.viz_type), spec.width
        )
        width = width if width in (3, 6, 12) else 6

        if width <= remaining:
            current_row.append((chart_id, spec))
            remaining -= width
        else:
            if current_row:
                rows.append(current_row)
            current_row = [(chart_id, spec)]
            remaining = 12 - width

    if current_row:
        rows.append(current_row)

    row_ids: list[str] = []
    for i, row in enumerate(rows):
        row_id = f"ROW_{i}"
        row_ids.append(row_id)
        chart_entry_ids: list[str] = []

        for chart_id, spec in row:
            width = FORCED_WIDTHS.get(
                VIZ_TYPE_MAP.get(spec.viz_type, spec.viz_type), spec.width
            )
            width = width if width in (3, 6, 12) else 6
            entry_id = f"CHART_{chart_id}"
            chart_entry_ids.append(entry_id)
            position[entry_id] = {
                "type": "CHART",
                "id": entry_id,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {
                    "chartId": int(chart_id),
                    "width": width,
                    "height": 50,
                },
            }

        position[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": chart_entry_ids,
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }

    position["GRID_ID"]["children"] = row_ids
    return position


class SupersetClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._username = username
        self._password = password
        # Persistent client — keeps session cookies alive across all requests
        self._session = httpx.Client(timeout=60)
        self._session.headers.update({"Content-Type": "application/json"})
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"

    def authenticate(self) -> None:
        resp = self._session.post(
            f"{self.base_url}/api/v1/security/login",
            json={
                "username": self._username,
                "password": self._password,
                "provider": "db",
                "refresh": True,
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Authentication failed [{resp.status_code}]: {resp.text}"
            )
        data = resp.json()
        jwt = data.get("access_token")
        if not jwt:
            raise RuntimeError(f"No access_token in login response: {resp.text}")
        self._session.headers["Authorization"] = f"Bearer {jwt}"

        csrf = self.get_csrf_token()
        self._session.headers["X-CSRFToken"] = csrf

    def get_csrf_token(self) -> str:
        resp = self._session.get(f"{self.base_url}/api/v1/security/csrf_token/")
        if resp.status_code != 200:
            raise RuntimeError(
                f"CSRF token fetch failed [{resp.status_code}]: {resp.text}"
            )
        return resp.json()["result"]

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        resp = self._session.request(method, url, **kwargs)

        if resp.status_code == 401:
            self.authenticate()
            resp = self._session.request(method, url, **kwargs)

        if not (200 <= resp.status_code < 300):
            raise RuntimeError(
                f"[{method} {path}] HTTP {resp.status_code}: {resp.text}"
            )
        return resp

    def get_dataset_by_name(self, name: str) -> DatasetInfo:
        rison_filter = f"(filters:!((col:table_name,opr:eq,value:'{name}')))"
        encoded = urllib.parse.quote(rison_filter)
        resp = self._request("GET", f"/api/v1/dataset/?q={encoded}")
        data = resp.json()
        results = data.get("result", [])
        if not results:
            # Try matching on dataset name directly
            rison_filter2 = f"(filters:!((col:datasource_name,opr:eq,value:'{name}')))"
            encoded2 = urllib.parse.quote(rison_filter2)
            resp2 = self._request("GET", f"/api/v1/dataset/?q={encoded2}")
            results = resp2.json().get("result", [])
        if not results:
            raise RuntimeError(
                f"Dataset '{name}' not found in Superset. "
                "Ensure the dataset exists and the name matches exactly."
            )
        ds = results[0]
        return self.get_dataset_columns(ds["id"])

    def get_dataset_columns(self, dataset_id: int) -> DatasetInfo:
        resp = self._request("GET", f"/api/v1/dataset/{dataset_id}")
        ds = resp.json()["result"]

        columns: list[DatasetColumn] = []
        for col in ds.get("columns", []):
            col_type = (col.get("type") or "STRING").upper()
            if "INT" in col_type or "FLOAT" in col_type or "DOUBLE" in col_type or "DECIMAL" in col_type or "NUMERIC" in col_type:
                normalized = "NUMERIC"
            elif "DATE" in col_type or "TIME" in col_type:
                normalized = "DATETIME"
            else:
                normalized = "STRING"

            columns.append(
                DatasetColumn(
                    column_name=col["column_name"],
                    type=normalized,
                    is_dttm=col.get("is_dttm", False),
                    expression=col.get("expression") or None,
                    distinct_values=None,
                )
            )

        metrics: list[dict] = []
        for m in ds.get("metrics", []):
            metrics.append(
                {
                    "id": m.get("id"),
                    "metric_name": m.get("metric_name"),
                    "expression": m.get("expression"),
                    "verbose_name": m.get("verbose_name"),
                }
            )

        return DatasetInfo(
            id=dataset_id,
            name=ds.get("table_name") or ds.get("datasource_name", ""),
            columns=columns,
            metrics=metrics,
        )

    def get_charts_for_dataset(self, dataset_id: int) -> list[dict]:
        rison_filter = f"(filters:!((col:datasource_id,opr:eq,value:{dataset_id})))"
        encoded = urllib.parse.quote(rison_filter)
        resp = self._request("GET", f"/api/v1/chart/?q={encoded}")
        results = resp.json().get("result", [])
        return [
            {"id": r["id"], "slice_name": r["slice_name"], "viz_type": r["viz_type"]}
            for r in results
        ]

    def _build_chart_payload(self, dataset_id: int, chart_spec: ChartSpec) -> dict:
        viz = VIZ_TYPE_MAP.get(chart_spec.viz_type, chart_spec.viz_type)
        params = build_chart_params(chart_spec)
        return {
            "slice_name": chart_spec.title,
            "viz_type": viz,
            "datasource_id": dataset_id,
            "datasource_type": "table",
            "params": json.dumps(params),
            "query_context": "{}",
        }

    def create_chart(self, dataset_id: int, chart_spec: ChartSpec) -> int:
        payload = self._build_chart_payload(dataset_id, chart_spec)
        resp = self._request("POST", "/api/v1/chart/", json=payload)
        return resp.json()["id"]

    def update_chart(self, chart_id: int, dataset_id: int, chart_spec: ChartSpec) -> int:
        payload = self._build_chart_payload(dataset_id, chart_spec)
        self._request("PUT", f"/api/v1/chart/{chart_id}", json=payload)
        return chart_id

    def upsert_chart(
        self,
        dataset_id: int,
        chart_spec: ChartSpec,
        existing_charts: list[dict],
    ) -> tuple[int, str]:
        match = next(
            (c for c in existing_charts if c["slice_name"] == chart_spec.title),
            None,
        )
        if match:
            chart_id = self.update_chart(match["id"], dataset_id, chart_spec)
            return chart_id, "updated"
        chart_id = self.create_chart(dataset_id, chart_spec)
        return chart_id, "created"

    def create_dashboard(
        self,
        title: str,
        chart_ids: list[int],
        position_json: dict,
    ) -> tuple[int, str]:
        resp = self._request(
            "POST",
            "/api/v1/dashboard/",
            json={"dashboard_title": title, "published": True},
        )
        dashboard_id = resp.json()["id"]
        self._set_dashboard_layout(dashboard_id, chart_ids, position_json)
        url = f"{self.base_url}/superset/dashboard/{dashboard_id}"
        return dashboard_id, url

    def _set_dashboard_layout(
        self, dashboard_id: int, chart_ids: list[int], position_json: dict
    ) -> None:
        # Step 1: set position_json layout
        self._request(
            "PUT",
            f"/api/v1/dashboard/{dashboard_id}",
            json={
                "position_json": json.dumps(position_json),
                "json_metadata": json.dumps({"default_filters": "{}"}),
            },
        )
        # Step 2: sync chart ownership directly via Superset's ORM.
        # The REST API has no writable /charts endpoint in Superset 5.x —
        # the dashboard_slices table must be updated through the model layer.
        self._sync_chart_ownership(dashboard_id, [int(cid) for cid in chart_ids])

    @staticmethod
    def _sync_chart_ownership(dashboard_id: int, chart_ids: list[int]) -> None:
        """
        Populate dashboard_slices by running a subprocess with Superset's
        Flask app context. This is necessary because Superset 5.x REST API
        does not expose a writable endpoint for chart-dashboard association.
        """
        script = f"""
import os, sys
os.environ['SUPERSET_CONFIG_PATH'] = '/home/yashaswiram/.superset/superset_config.py'
sys.path.insert(0, '/home/yashaswiram/.local/lib/python3.10/site-packages')
from superset.app import create_app
app = create_app()
with app.app_context():
    from superset import db
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice
    dash = db.session.get(Dashboard, {dashboard_id})
    if dash is None:
        print("Dashboard {dashboard_id} not found", file=sys.stderr)
        sys.exit(1)
    slices = db.session.query(Slice).filter(Slice.id.in_({chart_ids})).all()
    dash.slices = slices
    db.session.commit()
    print(f"Synced {{len(slices)}} chart(s) to dashboard {dashboard_id}")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Chart ownership sync failed for dashboard {dashboard_id}:\n"
                f"{result.stderr}"
            )
        # Print the confirmation line from stdout (filtered from Superset noise)
        for line in result.stdout.splitlines():
            if "Synced" in line:
                print(f"  [dim]{line}[/dim]")

    def update_dashboard(
        self,
        dashboard_id: int,
        chart_ids: list[int],
        position_json: dict,
    ) -> str:
        self._set_dashboard_layout(dashboard_id, chart_ids, position_json)
        url = f"{self.base_url}/superset/dashboard/{dashboard_id}"
        return url

    def get_dashboard(self, dashboard_id: int) -> dict:
        resp = self._request("GET", f"/api/v1/dashboard/{dashboard_id}")
        return resp.json()["result"]

    def set_dashboard_filters(
        self,
        dashboard_id: int,
        filters: list[FilterSpec],
        dataset_id: int,
    ) -> None:
        if not filters:
            return

        native_filters = []
        for f in filters:
            uid = uuid.uuid4().hex[:8].upper()
            filter_id = f"NATIVE_FILTER_{uid}"

            if f.filter_type == "time":
                filter_type = "filter_time"
            elif f.filter_type == "numerical":
                filter_type = "filter_range"
            else:
                filter_type = "filter_select"

            native_filters.append(
                {
                    "id": filter_id,
                    "name": f.label,
                    "filterType": filter_type,
                    "targets": [
                        {
                            "datasetId": dataset_id,
                            "column": {"name": f.column_name},
                        }
                    ],
                    "defaultDataMask": {
                        "filterState": {"value": f.default_value}
                    },
                    "controlValues": {
                        "multiSelect": True,
                        "enableEmptyFilter": False,
                    },
                    "cascadeParentIds": [],
                    "scope": {
                        "rootPath": ["ROOT_ID"],
                        "excluded": [],
                    },
                }
            )

        metadata = json.dumps(
            {
                "native_filter_configuration": native_filters,
                "default_filters": "{}",
            }
        )
        self._request(
            "PUT",
            f"/api/v1/dashboard/{dashboard_id}",
            json={"json_metadata": metadata},
        )
