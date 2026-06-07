#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import psycopg2


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


def q_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def config_from_env() -> PostgresConfig:
    return PostgresConfig(
        host=os.environ.get("RAW_PGHOST") or os.environ.get("PGHOST", "postgres"),
        port=int(os.environ.get("RAW_PGPORT") or os.environ.get("PGPORT", "5432")),
        user=os.environ.get("RAW_PGUSER") or os.environ.get("PGUSER", "airflow"),
        password=os.environ.get("RAW_PGPASSWORD") or os.environ.get("PGPASSWORD", "airflow"),
        database=os.environ.get("RAW_PGDATABASE") or os.environ.get("PGDATABASE", "airflow"),
    )


def connect(config: PostgresConfig):
    return psycopg2.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        dbname=config.database,
    )


def list_tables(cur, schema: str) -> list[str]:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_type = 'BASE TABLE'
          AND table_name NOT LIKE '\\_%%'
        ORDER BY table_name
        """,
        (schema,),
    )
    return [row[0] for row in cur.fetchall()]


def table_columns(cur, schema: str, table: str) -> list[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    return [row[0] for row in cur.fetchall()]


def table_count(cur, schema: str, table: str) -> int:
    cur.execute(f"SELECT count(*) FROM {q_ident(schema)}.{q_ident(table)}")
    return int(cur.fetchone()[0])


def column_fill_stats(cur, schema: str, table: str, columns: list[str]) -> list[tuple[str, int]]:
    if not columns:
        return []
    expressions = [
        f"count(NULLIF(trim({q_ident(column)}::text), '')) AS {q_ident(column)}"
        for column in columns
    ]
    cur.execute(
        f"SELECT {', '.join(expressions)} FROM {q_ident(schema)}.{q_ident(table)}"
    )
    counts = cur.fetchone()
    return list(zip(columns, [int(value or 0) for value in counts]))


def sample_rows(cur, schema: str, table: str, columns: list[str], limit: int) -> list[dict[str, str]]:
    if not columns or limit <= 0:
        return []
    sample_columns = columns[: min(len(columns), 8)]
    cur.execute(
        f"""
        SELECT {', '.join(q_ident(column) for column in sample_columns)}
        FROM {q_ident(schema)}.{q_ident(table)}
        LIMIT %s
        """,
        (limit,),
    )
    rows = []
    for db_row in cur.fetchall():
        rows.append(dict(zip(sample_columns, db_row)))
    return rows


def print_table_report(cur, schema: str, table: str, *, sample_limit: int, top_columns: int) -> None:
    columns = table_columns(cur, schema, table)
    rows_count = table_count(cur, schema, table)
    print(f"\n{schema}.{table}")
    print("-" * (len(schema) + len(table) + 1))
    print(f"rows: {rows_count}")
    print(f"columns: {len(columns)}")
    print("column names:")
    print("  " + ", ".join(columns))

    if rows_count > 0:
        stats = column_fill_stats(cur, schema, table, columns)
        stats = sorted(stats, key=lambda item: item[1], reverse=True)
        print(f"most filled columns, top {min(top_columns, len(stats))}:")
        for column, filled in stats[:top_columns]:
            pct = filled / rows_count * 100
            print(f"  {column}: {filled}/{rows_count} ({pct:.1f}%)")
    else:
        print("most filled columns: table is empty")

    samples = sample_rows(cur, schema, table, columns, sample_limit)
    if samples:
        print(f"sample rows, first {len(samples)}:")
        for i, row in enumerate(samples, 1):
            compact = {key: shorten(value) for key, value in row.items()}
            print(f"  {i}. {compact}")


def shorten(value: object, limit: int = 80) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def main() -> int:
    parser = argparse.ArgumentParser(description="Quick analytics for raw Postgres tables.")
    parser.add_argument("--schema", default=os.environ.get("RAW_SCHEMA", "raw"))
    parser.add_argument("--tables", default="", help="Comma-separated table names. Empty means all user tables.")
    parser.add_argument("--sample", type=int, default=2, help="Sample rows per table.")
    parser.add_argument("--top-columns", type=int, default=10, help="How many fill-rate columns to show.")
    args = parser.parse_args()

    requested_tables = [item.strip() for item in args.tables.split(",") if item.strip()]

    with connect(config_from_env()) as conn:
        with conn.cursor() as cur:
            tables = requested_tables or list_tables(cur, args.schema)
            if not tables:
                print(f"No tables found in schema {args.schema}.")
                return 0

            print(f"schema: {args.schema}")
            print(f"tables: {len(tables)}")
            for table in tables:
                print_table_report(
                    cur,
                    args.schema,
                    table,
                    sample_limit=args.sample,
                    top_columns=args.top_columns,
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
