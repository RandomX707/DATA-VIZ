from __future__ import annotations

from models.schemas import DatasetColumn, DatasetInfo
from tools.superset_api import SupersetClient


class ColumnSampler:
    def __init__(self, superset_client: SupersetClient):
        self.client = superset_client

    def enrich_columns(self, dataset_info: DatasetInfo) -> DatasetInfo:
        enriched: list[DatasetColumn] = []
        for col in dataset_info.columns:
            if col.type == "STRING":
                col = self._sample_column(dataset_info, col)
            enriched.append(col)
        dataset_info.columns = enriched
        return dataset_info

    def _sample_column(
        self, dataset_info: DatasetInfo, col: DatasetColumn
    ) -> DatasetColumn:
        try:
            values = self._fetch_via_sqllab(dataset_info, col.column_name)
            if values is not None and len(values) <= 20:
                col.distinct_values = values
        except Exception:
            pass  # Leave distinct_values as None, never crash the pipeline
        return col

    def _fetch_via_sqllab(
        self, dataset_info: DatasetInfo, column_name: str
    ) -> list[str] | None:
        # Build a query against the dataset
        # For physical tables use table_name; for virtual datasets use the sql property
        table_ref = self._get_table_ref(dataset_info)
        sql = (
            f"SELECT DISTINCT {self._quote(column_name)} "
            f"FROM {table_ref} "
            f"ORDER BY {self._quote(column_name)} "
            f"LIMIT 21"
        )

        database_id = self._get_database_id(dataset_info.id)
        if database_id is None:
            return None

        resp = self.client._request(
            "POST",
            "/api/v1/sqllab/execute/",
            json={
                "database_id": database_id,
                "sql": sql,
                "runAsync": False,
                "queryLimit": 21,
            },
        )
        data = resp.json()
        rows = data.get("data", [])
        if len(rows) == 21:
            return None  # High cardinality
        return [str(list(r.values())[0]) for r in rows if list(r.values())[0] is not None]

    def _get_database_id(self, dataset_id: int) -> int | None:
        try:
            resp = self.client._request("GET", f"/api/v1/dataset/{dataset_id}")
            return resp.json()["result"].get("database", {}).get("id")
        except Exception:
            return None

    def _get_table_ref(self, dataset_info: DatasetInfo) -> str:
        try:
            resp = self.client._request("GET", f"/api/v1/dataset/{dataset_info.id}")
            ds = resp.json()["result"]
            sql = ds.get("sql")
            if sql and sql.strip():
                return f"({sql.strip()}) AS _t"
            schema = ds.get("schema")
            table = ds.get("table_name", dataset_info.name)
            if schema:
                return f"{schema}.{table}"
            return table
        except Exception:
            return dataset_info.name

    @staticmethod
    def _quote(name: str) -> str:
        safe = name.replace('"', '""')
        return f'"{safe}"'
