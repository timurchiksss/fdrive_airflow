#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import psycopg2
from psycopg2.extras import execute_values


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
        host=os.environ.get("DB_HOST") or os.environ.get("PGHOST") or os.environ.get("RAW_PGHOST", "postgres"),
        port=int(os.environ.get("DB_PORT") or os.environ.get("PGPORT") or os.environ.get("RAW_PGPORT", "5432")),
        user=os.environ.get("DB_USER") or os.environ.get("PGUSER") or os.environ.get("RAW_PGUSER", "airflow"),
        password=os.environ.get("DB_PASSWORD") or os.environ.get("PGPASSWORD") or os.environ.get("RAW_PGPASSWORD", "airflow"),
        database=os.environ.get("DB_NAME") or os.environ.get("PGDATABASE") or os.environ.get("RAW_PGDATABASE", "airflow"),
    )


def connect(config: PostgresConfig):
    return psycopg2.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        dbname=config.database,
    )


def table_exists(cur, schema: str, table: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_name = %s
        )
        """,
        (schema, table),
    )
    return bool(cur.fetchone()[0])


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


def list_clean_tables(cur, clean_schema: str) -> list[str]:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_type = 'BASE TABLE'
          AND table_name NOT LIKE '\\_%%'
        ORDER BY table_name
        """,
        (clean_schema,),
    )
    return [row[0] for row in cur.fetchall()]


def python_value(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def text_value(value) -> str | None:
    if value is None:
        return None
    value = python_value(value)
    text = str(value).strip()
    return text if text and text.lower() not in {"nan", "none", "null"} else None


def iter_cursor_batches(cur, size: int = 10_000):
    while True:
        batch = cur.fetchmany(size)
        if not batch:
            break
        yield batch


def load_sku_map(cur, match_schema: str) -> dict[tuple[str, str], str]:
    cur.execute(
        f"""
        SELECT DISTINCT ON (source, source_product_id)
               source, source_product_id, sku_id
        FROM {q_ident(match_schema)}.sku_source_mapping
        ORDER BY source, source_product_id, match_score DESC NULLS LAST
        """
    )
    return {
        (str(source), str(source_product_id)): sku_id
        for source, source_product_id, sku_id in cur.fetchall()
        if source is not None and source_product_id is not None and sku_id is not None
    }


def ensure_price_history_table(cur, match_schema: str) -> None:
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {q_ident(match_schema)}")
    cur.execute(
        """
        DO $$
        DECLARE
            s text := %s;
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = format('%%I.skus', s)::regclass
                  AND contype = 'p'
            ) THEN
                BEGIN
                    EXECUTE format('ALTER TABLE %%I.skus ADD CONSTRAINT skus_pkey PRIMARY KEY (id)', s);
                EXCEPTION
                    WHEN duplicate_object OR invalid_table_definition THEN
                        NULL;
                END;
            END IF;
        END $$;
        """,
        (match_schema,),
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {q_ident(match_schema)}.sku_price_history (
            captured_at timestamptz NOT NULL,
            price_date date,
            sku_id text REFERENCES {q_ident(match_schema)}.skus(id),
            source text NOT NULL,
            source_product_id text NOT NULL,
            seller_name text,
            city text,
            price double precision,
            old_price double precision,
            discount_price double precision,
            currency text,
            availability text,
            parsed_at timestamptz,
            CONSTRAINT uq_sph UNIQUE (source, source_product_id, captured_at)
        )
        """
    )
    cur.execute(f"ALTER TABLE {q_ident(match_schema)}.sku_price_history DROP COLUMN IF EXISTS loaded_at")
    cur.execute(f"CREATE INDEX IF NOT EXISTS ix_sph_sku ON {q_ident(match_schema)}.sku_price_history (sku_id)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS ix_sph_date ON {q_ident(match_schema)}.sku_price_history (price_date)")
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS ix_sph_cap "
        f"ON {q_ident(match_schema)}.sku_price_history (source, source_product_id, captured_at)"
    )


def build_sku_price_history(clean_schema: str, match_schema: str, config: PostgresConfig | None = None) -> int:
    with connect(config or config_from_env()) as conn:
        with conn.cursor() as cur:
            if not table_exists(cur, match_schema, "skus"):
                raise RuntimeError(f"Required table {match_schema}.skus does not exist.")
            if not table_exists(cur, match_schema, "sku_source_mapping"):
                raise RuntimeError(f"Required table {match_schema}.sku_source_mapping does not exist.")

            ensure_price_history_table(cur, match_schema)
            sku_map = load_sku_map(cur, match_schema)
            rows = {}
            total_upserted = 0

            def flush_rows() -> None:
                nonlocal total_upserted
                upsert_rows = list(rows.values())
                if not upsert_rows:
                    return
                with conn.cursor() as write_cur:
                    execute_values(
                        write_cur,
                        f"""
                        INSERT INTO {q_ident(match_schema)}.sku_price_history
                            (captured_at, price_date, sku_id, source, source_product_id, seller_name,
                             city, price, old_price, discount_price, currency, availability, parsed_at)
                        VALUES %s
                        ON CONFLICT (source, source_product_id, captured_at) DO UPDATE
                          SET price = EXCLUDED.price,
                              old_price = EXCLUDED.old_price,
                              discount_price = EXCLUDED.discount_price,
                              currency = EXCLUDED.currency,
                              availability = EXCLUDED.availability,
                              sku_id = EXCLUDED.sku_id,
                              parsed_at = EXCLUDED.parsed_at
                        """,
                        upsert_rows,
                        page_size=5000,
                    )
                total_upserted += len(upsert_rows)
                rows.clear()

            for table in list_clean_tables(cur, clean_schema):
                columns = table_columns(cur, clean_schema, table)
                if not {"source", "source_product_id", "price"} <= columns:
                    continue

                selected = [
                    column for column in (
                        "source",
                        "source_product_id",
                        "city",
                        "price",
                        "old_price",
                        "currency",
                        "availability",
                        "parsed_at",
                        "loaded_at",
                    )
                    if column in columns
                ]
                cur.execute(
                    f"""
                    SELECT {", ".join(q_ident(column) for column in selected)}
                    FROM {q_ident(clean_schema)}.{q_ident(table)}
                    WHERE price IS NOT NULL
                    """
                )
                result_columns = [desc[0] for desc in cur.description]
                for batch in iter_cursor_batches(cur):
                    for raw_row in batch:
                        record = dict(zip(result_columns, raw_row))
                        source = text_value(record.get("source"))
                        source_product_id = text_value(record.get("source_product_id"))
                        if not source or not source_product_id:
                            continue

                        captured_at = record.get("loaded_at") or datetime.now(timezone.utc)
                        price = python_value(record.get("price"))
                        old_price = python_value(record.get("old_price"))
                        discount_price = price if old_price is not None and price is not None and old_price > price else None
                        parsed_at = record.get("parsed_at")
                        if parsed_at == "":
                            parsed_at = None
                        if parsed_at is None:
                            parsed_at = captured_at

                        row = (
                            captured_at,
                            captured_at.date() if hasattr(captured_at, "date") else None,
                            sku_map.get((source, source_product_id)),
                            source,
                            source_product_id,
                            source,
                            text_value(record.get("city")),
                            price,
                            old_price,
                            discount_price,
                            text_value(record.get("currency")),
                            text_value(record.get("availability")),
                            parsed_at,
                        )
                        rows[(source, source_product_id, captured_at)] = row
                        if len(rows) >= 10_000:
                            flush_rows()

            flush_rows()
            print(f"sku_price_history upserted rows: {total_upserted}", flush=True)
            return total_upserted


def main() -> int:
    parser = argparse.ArgumentParser(description="Build matching.sku_price_history from cleanned tables.")
    parser.add_argument("--clean-schema", default=os.environ.get("CLEAN_SCHEMA", "cleanned"))
    parser.add_argument("--match-schema", default=os.environ.get("MATCH_SCHEMA", "matching"))
    args = parser.parse_args()
    build_sku_price_history(args.clean_schema, args.match_schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
