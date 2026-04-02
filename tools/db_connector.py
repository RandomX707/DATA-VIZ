from __future__ import annotations

from models.schemas import ColumnProfile, TableProfile


class DBConnector:
    """Handles all direct database operations for Phase 1 and Phase 2.

    Supports PostgreSQL and MySQL via SQLAlchemy, MongoDB via pymongo.
    Connections are lazy — nothing is created until the first actual call.
    All public methods return tuples or values; they never raise.
    """

    def __init__(
        self,
        db_type: str,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
    ) -> None:
        self.db_type = db_type
        self.host = host
        self.port = int(port)
        self.database = database
        self.username = username
        self.password = password
        self._engine = None
        self._mongo_client = None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_engine(self):
        from sqlalchemy import create_engine

        if self.db_type == "postgresql":
            uri = (
                f"postgresql+psycopg2://{self.username}:{self.password}"
                f"@{self.host}:{self.port}/{self.database}"
            )
        elif self.db_type == "mysql":
            uri = (
                f"mysql+pymysql://{self.username}:{self.password}"
                f"@{self.host}:{self.port}/{self.database}"
            )
        else:
            raise ValueError(f"Unsupported db_type for SQLAlchemy: {self.db_type}")
        return create_engine(uri, pool_pre_ping=True)

    def _get_engine(self):
        if self._engine is None:
            self._engine = self._build_engine()
        return self._engine

    def _get_mongo_client(self):
        if self._mongo_client is None:
            import pymongo

            uri = (
                f"mongodb://{self.username}:{self.password}"
                f"@{self.host}:{self.port}/{self.database}"
            )
            self._mongo_client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
        return self._mongo_client

    # ── Public API ────────────────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """Try a simple query. Returns (True, 'Connected') or (False, error_message)."""
        try:
            if self.db_type == "mongodb":
                client = self._get_mongo_client()
                client.admin.command("ping")
                return True, "Connected"
            else:
                from sqlalchemy import text

                with self._get_engine().connect() as conn:
                    conn.execute(text("SELECT 1"))
                return True, "Connected"
        except Exception as exc:
            return False, str(exc)

    def get_all_tables(self) -> list[str]:
        """Return sorted list of all table/collection names in the database."""
        if self.db_type == "mongodb":
            client = self._get_mongo_client()
            return sorted(client[self.database].list_collection_names())

        from sqlalchemy import text

        if self.db_type == "postgresql":
            sql = (
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
        else:  # mysql
            sql = (
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
        with self._get_engine().connect() as conn:
            result = conn.execute(text(sql))
            return [row[0] for row in result]

    def profile_table(self, table_name: str) -> TableProfile:
        """Profile a single table: row count, column types, sample values, null %."""
        if self.db_type == "mongodb":
            return self._profile_mongo_collection(table_name)
        return self._profile_sql_table(table_name)

    def _profile_sql_table(self, table_name: str) -> TableProfile:
        from sqlalchemy import inspect, text

        engine = self._get_engine()
        inspector = inspect(engine)
        columns_info = inspector.get_columns(table_name)

        with engine.connect() as conn:
            # Row count
            row_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table_name}")
            ).scalar() or 0

            # 3 sample rows
            sample_result = conn.execute(
                text(f"SELECT * FROM {table_name} LIMIT 3")
            )
            sample_rows = [
                {k: (str(v) if v is not None else None) for k, v in zip(sample_result.keys(), row)}
                for row in sample_result
            ]

            column_profiles: list[ColumnProfile] = []
            for col_info in columns_info:
                col_name = col_info["name"]
                col_type = str(col_info["type"])

                # Null percentage
                try:
                    null_count = (
                        conn.execute(
                            text(
                                f"SELECT COUNT(*) FROM {table_name} "
                                f"WHERE {col_name} IS NULL"
                            )
                        ).scalar()
                        or 0
                    )
                    null_pct = (null_count / row_count * 100) if row_count > 0 else 0.0
                except Exception:
                    null_pct = 0.0

                # Up to 5 non-null distinct sample values
                try:
                    sv_result = conn.execute(
                        text(
                            f"SELECT DISTINCT {col_name} FROM {table_name} "
                            f"WHERE {col_name} IS NOT NULL LIMIT 5"
                        )
                    )
                    sample_values = [str(r[0]) for r in sv_result]
                except Exception:
                    sample_values = []

                col_lower = col_name.lower()
                type_upper = col_type.upper()
                is_likely_pk = col_lower == "id" or col_lower.endswith("_id")
                is_likely_fk = (
                    col_lower.endswith("_id")
                    and col_lower != "id"
                    and table_name.lower() not in col_lower
                )
                is_likely_date = any(
                    t in type_upper for t in ("DATE", "TIME", "TIMESTAMP")
                )

                column_profiles.append(
                    ColumnProfile(
                        column_name=col_name,
                        data_type=col_type,
                        sample_values=sample_values,
                        null_pct=round(null_pct, 2),
                        is_likely_pk=is_likely_pk,
                        is_likely_fk=is_likely_fk,
                        is_likely_date=is_likely_date,
                    )
                )

        return TableProfile(
            table_name=table_name,
            row_count=int(row_count),
            columns=column_profiles,
            sample_rows=sample_rows,
        )

    def _profile_mongo_collection(self, collection_name: str) -> TableProfile:
        client = self._get_mongo_client()
        coll = client[self.database][collection_name]

        row_count = coll.count_documents({})
        sample_docs = list(coll.find({}, {"_id": 0}).limit(3))
        sample_rows = [{k: str(v) for k, v in doc.items()} for doc in sample_docs]

        # Infer schema from first 20 documents
        schema_docs = list(coll.find({}, {"_id": 0}).limit(20))
        field_types: dict[str, str] = {}
        field_null_counts: dict[str, int] = {}

        for doc in schema_docs:
            for k, v in doc.items():
                if k not in field_types:
                    field_types[k] = type(v).__name__
                if v is None:
                    field_null_counts[k] = field_null_counts.get(k, 0) + 1

        column_profiles: list[ColumnProfile] = []
        for field_name, field_type in field_types.items():
            null_pct = (
                (field_null_counts.get(field_name, 0) / len(schema_docs) * 100)
                if schema_docs
                else 0.0
            )
            sample_values = [
                str(doc[field_name])
                for doc in schema_docs[:5]
                if doc.get(field_name) is not None
            ][:5]

            col_lower = field_name.lower()
            is_likely_pk = col_lower == "id" or col_lower.endswith("_id")
            is_likely_fk = col_lower.endswith("_id") and col_lower != "id"
            is_likely_date = (
                "date" in col_lower
                or "time" in col_lower
                or field_type in ("datetime", "date")
            )

            column_profiles.append(
                ColumnProfile(
                    column_name=field_name,
                    data_type=field_type,
                    sample_values=sample_values,
                    null_pct=round(null_pct, 2),
                    is_likely_pk=is_likely_pk,
                    is_likely_fk=is_likely_fk,
                    is_likely_date=is_likely_date,
                )
            )

        return TableProfile(
            table_name=collection_name,
            row_count=row_count,
            columns=column_profiles,
            sample_rows=sample_rows,
        )

    def run_query(self, sql: str, limit: int = 100) -> tuple[bool, list[dict], str]:
        """Execute sql with LIMIT applied. Returns (ok, rows, error)."""
        try:
            if self.db_type == "mongodb":
                return False, [], "Direct SQL queries are not supported for MongoDB."
            from sqlalchemy import text

            sql = sql.strip().rstrip(';')
            limited_sql = f"SELECT * FROM ({sql}) _q LIMIT {limit}"
            with self._get_engine().connect() as conn:
                result = conn.execute(text(limited_sql))
                rows = []
                for row in result:
                    rows.append(
                        {
                            k: (
                                v
                                if isinstance(v, (int, float, bool, type(None)))
                                else str(v)
                            )
                            for k, v in zip(result.keys(), row)
                        }
                    )
            return True, rows, ""
        except Exception as exc:
            return False, [], str(exc)

    def get_row_count(self, sql: str) -> tuple[bool, int, str]:
        """Run SELECT COUNT(*) FROM (sql). Returns (ok, count, error)."""
        try:
            from sqlalchemy import text

            sql = sql.strip().rstrip(';')
            count_sql = f"SELECT COUNT(*) FROM ({sql}) _count_q"
            with self._get_engine().connect() as conn:
                count = conn.execute(text(count_sql)).scalar() or 0
            return True, int(count), ""
        except Exception as exc:
            return False, 0, str(exc)

    def check_duplicates(self, sql: str) -> tuple[bool, int, str]:
        """Compare total row count vs distinct row count. Returns (ok, dup_count, error)."""
        try:
            from sqlalchemy import text

            sql = sql.strip().rstrip(';')
            total_sql = f"SELECT COUNT(*) FROM ({sql}) _total"
            distinct_sql = (
                f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM ({sql}) _inner) _distinct"
            )
            with self._get_engine().connect() as conn:
                total = conn.execute(text(total_sql)).scalar() or 0
                distinct = conn.execute(text(distinct_sql)).scalar() or 0
            return True, int(total - distinct), ""
        except Exception as exc:
            return False, 0, str(exc)
