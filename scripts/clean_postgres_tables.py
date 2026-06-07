#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values


warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy connectable.*")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

_CLEANING_FUNCS = None


def cleaning_funcs():
    global _CLEANING_FUNCS
    if _CLEANING_FUNCS is not None:
        return _CLEANING_FUNCS

    try:
        from cleaning_all import (  # noqa: E402
            BRAND_DICT,
            clean_brand,
            clean_price,
            normalize_availability,
            normalize_bool,
            normalize_diameter,
            normalize_engine_type,
            normalize_oil_type,
            normalize_season,
            normalize_speed_index,
            normalize_viscosity,
            normalize_volume,
            normalized_name,
        )
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "cleaning_all.py is not available inside Airflow. "
            "Make sure docker-compose.yaml mounts ./cleaning_all.py to /opt/airflow/cleaning_all.py "
            "and recreate airflow-webserver/airflow-scheduler containers."
        ) from exc

    _CLEANING_FUNCS = {
        "BRAND_DICT": BRAND_DICT,
        "clean_brand": clean_brand,
        "clean_price": clean_price,
        "normalize_availability": normalize_availability,
        "normalize_bool": normalize_bool,
        "normalize_diameter": normalize_diameter,
        "normalize_engine_type": normalize_engine_type,
        "normalize_oil_type": normalize_oil_type,
        "normalize_season": normalize_season,
        "normalize_speed_index": normalize_speed_index,
        "normalize_viscosity": normalize_viscosity,
        "normalize_volume": normalize_volume,
        "normalized_name": normalized_name,
    }
    return _CLEANING_FUNCS


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


NUMERIC_COLUMNS = {
    "price",
    "old_price",
    "tire_width",
    "tire_profile",
    "tire_diameter",
    "wheel_width",
    "wheel_diameter",
    "volume_liters",
    "capacity_ah",
    "voltage_v",
    "start_current_a",
}

BOOLEAN_COLUMNS = {"studded", "runflat"}

AUDIT_COLUMNS = {"source_file", "loaded_at", "load_id"}


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


def read_table(conn, schema: str, table: str) -> pd.DataFrame:
    sql = f"SELECT * FROM {q_ident(schema)}.{q_ident(table)}"
    return pd.read_sql_query(sql, conn)


def clean_table(df: pd.DataFrame, table: str) -> pd.DataFrame:
    funcs = cleaning_funcs()
    df = df.copy()

    if "product_name" in df.columns:
        df["product_name"] = df["product_name"].astype("string").str.strip()
        df["normalized_name"] = df["product_name"].apply(funcs["normalized_name"])

    if "brand" in df.columns:
        df["brand"] = df["brand"].apply(lambda value: funcs["clean_brand"](value, funcs["BRAND_DICT"]))

    for column in ["price", "old_price"]:
        if column in df.columns:
            df[column] = df[column].apply(funcs["clean_price"])

    if "availability" in df.columns:
        df["availability"] = df["availability"].apply(funcs["normalize_availability"])

    if "season" in df.columns:
        df["season"] = df["season"].apply(funcs["normalize_season"])

    for column in ["tire_diameter", "wheel_diameter"]:
        if column in df.columns:
            df[column] = df[column].apply(funcs["normalize_diameter"])

    for column in ["tire_width", "tire_profile", "wheel_width", "capacity_ah", "voltage_v", "start_current_a"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    if "speed_index" in df.columns:
        df["speed_index"] = df["speed_index"].apply(funcs["normalize_speed_index"])

    for column in BOOLEAN_COLUMNS:
        if column in df.columns:
            df[column] = df[column].apply(funcs["normalize_bool"])

    if "viscosity" in df.columns:
        df["viscosity"] = df["viscosity"].apply(funcs["normalize_viscosity"])
    if "volume_liters" in df.columns:
        df["volume_liters"] = df["volume_liters"].apply(funcs["normalize_volume"])
    if "oil_type" in df.columns:
        df["oil_type"] = df["oil_type"].apply(funcs["normalize_oil_type"])
    if "engine_type" in df.columns:
        df["engine_type"] = df["engine_type"].apply(funcs["normalize_engine_type"])

    subset = [column for column in ["load_id", "source", "source_product_id", "source_url"] if column in df.columns]
    if "load_id" not in subset:
        subset = [column for column in ["source", "source_product_id", "source_url"] if column in df.columns]
    if subset:
        before = len(df)
        df = df.drop_duplicates(subset=subset, keep="first")
        removed = before - len(df)
        if removed:
            print(f"  [{table}] removed duplicate products: {removed}", flush=True)
    else:
        df = df.drop_duplicates()

    df["cleaned_at"] = datetime.now(timezone.utc)
    return df


def column_type(column: str, series: pd.Series) -> str:
    if column in BOOLEAN_COLUMNS:
        return "boolean"
    if column in NUMERIC_COLUMNS:
        return "double precision"
    if column == "cleaned_at":
        return "timestamptz"
    if column == "loaded_at":
        return "timestamptz"
    return "text"


def python_value(value):
    if pd.isna(value):
        return None
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    if hasattr(value, "item"):
        return value.item()
    return value


def table_columns(cur, schema: str, table: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        """,
        (schema, table),
    )
    return {row[0] for row in cur.fetchall()}


def ensure_table(cur, schema: str, table: str, df: pd.DataFrame) -> None:
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {q_ident(schema)}")

    definitions = ", ".join(
        f"{q_ident(column)} {column_type(column, df[column])}"
        for column in df.columns
    )
    cur.execute(f"CREATE TABLE IF NOT EXISTS {q_ident(schema)}.{q_ident(table)} ({definitions})")

    existing = table_columns(cur, schema, table)
    for column in df.columns:
        if column not in existing:
            cur.execute(
                f"ALTER TABLE {q_ident(schema)}.{q_ident(table)} "
                f"ADD COLUMN {q_ident(column)} {column_type(column, df[column])}"
            )
            existing.add(column)


def append_table(cur, schema: str, table: str, df: pd.DataFrame) -> None:
    ensure_table(cur, schema, table, df)

    if df.empty:
        return

    if "load_id" in df.columns:
        load_ids = [value for value in df["load_id"].dropna().unique().tolist()]
        if load_ids:
            cur.execute(
                f"DELETE FROM {q_ident(schema)}.{q_ident(table)} WHERE load_id = ANY(%s)",
                (load_ids,),
            )

    columns_sql = ", ".join(q_ident(column) for column in df.columns)
    rows = [
        tuple(python_value(value) for value in row)
        for row in df.itertuples(index=False, name=None)
    ]
    execute_values(
        cur,
        f"INSERT INTO {q_ident(schema)}.{q_ident(table)} ({columns_sql}) VALUES %s",
        rows,
        page_size=1000,
    )


def clean_database(raw_schema: str, clean_schema: str, tables: list[str] | None = None) -> None:
    with connect(config_from_env()) as conn:
        with conn.cursor() as cur:
            raw_tables = tables or list_tables(cur, raw_schema)
            print(f"raw schema: {raw_schema}")
            print(f"clean schema: {clean_schema}")
            print(f"tables to clean: {len(raw_tables)}")

            cleaned_tables = set()
            for table in raw_tables:
                raw_df = read_table(conn, raw_schema, table)
                print(f"\n[{table}] raw rows={len(raw_df)}, columns={len(raw_df.columns)}", flush=True)
                clean_df = clean_table(raw_df, table)
                print(f"[{table}] clean rows={len(clean_df)}, columns={len(clean_df.columns)}", flush=True)
                append_table(cur, clean_schema, table, clean_df)
                cleaned_tables.add(table)

            if cleaned_tables:
                print(
                    f"cleaned {len(cleaned_tables)} tables in append mode; "
                    "obsolete cleaned tables were left untouched",
                    flush=True,
                )


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean raw Postgres catalog tables into cleanned schema.")
    parser.add_argument("--raw-schema", default=os.environ.get("RAW_SCHEMA", "raw"))
    parser.add_argument("--clean-schema", default=os.environ.get("CLEAN_SCHEMA", "cleanned"))
    parser.add_argument("--tables", default="", help="Comma-separated raw table names. Empty means all raw tables.")
    args = parser.parse_args()

    tables = [item.strip() for item in args.tables.split(",") if item.strip()] or None
    clean_database(args.raw_schema, args.clean_schema, tables=tables)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
