#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from raw_postgres_loader import (
    PostgresConfig,
    config_from_env,
    connect,
    create_empty_table,
    ensure_database_exists,
    ensure_metadata,
    q_ident,
)


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


class StreamingRawWriter:
    def __init__(
        self,
        *,
        config: PostgresConfig | None = None,
        schema: str = "raw",
        load_id: str,
        source_file: str | Path,
        create_database: bool = False,
        maintenance_database: str = "postgres",
    ) -> None:
        self.config = config or config_from_env()
        self.schema = schema
        self.load_id = load_id
        self.source_file = str(source_file)
        self.cleared: set[str] = set()
        if create_database:
            ensure_database_exists(self.config, maintenance_database=maintenance_database)
        self.conn = connect(self.config)
        self.row_counts: dict[str, int] = {}
        with self.conn.cursor() as cur:
            ensure_metadata(cur, schema)
        self.conn.commit()

    @classmethod
    def from_env(
        cls,
        *,
        schema: str,
        load_id: str,
        source_file: str | Path,
        create_database: bool = False,
        maintenance_database: str = "postgres",
    ) -> "StreamingRawWriter":
        return cls(
            config=config_from_env(),
            schema=schema,
            load_id=load_id,
            source_file=source_file,
            create_database=create_database,
            maintenance_database=maintenance_database,
        )

    def write_rows(
        self,
        table: str,
        rows: Iterable[dict[str, Any]],
        columns: list[str],
    ) -> int:
        batch = list(rows)
        if not batch:
            return 0

        column_pairs = [(column, column) for column in columns]
        db_cols = ", ".join(q_ident(column) for column in columns)
        placeholders = ", ".join(["%s"] * (len(columns) + 2))
        values = [
            tuple(text_value(row.get(column, "")) for column in columns)
            + (self.source_file, self.load_id)
            for row in batch
        ]

        with self.conn.cursor() as cur:
            create_empty_table(cur, self.schema, table, column_pairs)
            if table not in self.cleared:
                cur.execute(
                    f"""
                    DELETE FROM {q_ident(self.schema)}.{q_ident(table)}
                    WHERE load_id = %s AND source_file = %s
                    """,
                    (self.load_id, self.source_file),
                )
                cur.execute(
                    f"""
                    DELETE FROM {q_ident(self.schema)}._load_files
                    WHERE load_id = %s AND table_name = %s AND source_file = %s
                    """,
                    (self.load_id, table, self.source_file),
                )
                self.cleared.add(table)

            cur.executemany(
                f"""
                INSERT INTO {q_ident(self.schema)}.{q_ident(table)}
                    ({db_cols}, source_file, load_id)
                VALUES ({placeholders})
                """,
                values,
            )
            cur.execute(
                f"DELETE FROM {q_ident(self.schema)}._column_map WHERE table_name = %s",
                (table,),
            )
            cur.executemany(
                f"""
                INSERT INTO {q_ident(self.schema)}._column_map
                    (table_name, column_position, db_column_name, source_column_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (table_name, column_position) DO UPDATE
                SET db_column_name = EXCLUDED.db_column_name,
                    source_column_name = EXCLUDED.source_column_name
                """,
                [(table, i, column, column) for i, column in enumerate(columns, 1)],
            )
            self.row_counts[table] = self.row_counts.get(table, 0) + len(batch)
            cur.execute(
                f"""
                INSERT INTO {q_ident(self.schema)}._load_files
                    (load_id, table_name, source_file, row_count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (load_id, table_name, source_file) DO UPDATE
                SET row_count = EXCLUDED.row_count,
                    loaded_at = now()
                """,
                (self.load_id, table, self.source_file, self.row_counts[table]),
            )
        self.conn.commit()
        return len(batch)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "StreamingRawWriter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
