#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
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


ATTRIBUTE_GROUPS = {
    1: "Основные",
    2: "Технические характеристики",
    3: "Размеры",
    4: "Совместимость",
    5: "Дополнительно",
}

ATTRIBUTES = [
    ("brand", "text", 1),
    ("product_line", "text", 1),
    ("oil_type", "text", 1),
    ("engine_type", "text", 1),
    ("battery_type", "text", 1),
    ("filter_type", "text", 1),
    ("season", "text", 1),
    ("studded", "boolean", 1),
    ("runflat", "boolean", 1),
    ("package_type", "text", 1),
    ("polarity", "text", 1),
    ("terminal_type", "text", 1),
    ("viscosity", "text", 2),
    ("volume_liters", "liters", 2),
    ("capacity_ah", "Ah", 2),
    ("voltage_v", "V", 2),
    ("start_current_a", "A", 2),
    ("load_index", "text", 2),
    ("speed_index", "text", 2),
    ("tire_width", "mm", 2),
    ("tire_profile", "percent", 2),
    ("tire_diameter", "inch", 2),
    ("acea_class", "text", 2),
    ("specification", "text", 2),
    ("approvals", "text", 2),
    ("width", "mm", 3),
    ("height", "mm", 3),
    ("length", "mm", 3),
    ("dimensions", "text", 3),
    ("weight", "text", 3),
    ("compatible_brand", "text", 4),
    ("compatible_model", "text", 4),
    ("oem_number", "text", 4),
    ("features", "text", 5),
    ("additional_information", "text", 5),
    ("image_url", "text", 5),
]

DOMAIN_ATTRIBUTES = {
    "oils": {
        "brand", "product_line", "viscosity", "volume_liters", "oil_type", "engine_type",
        "specification", "package_type", "acea_class", "approvals", "image_url",
    },
    "tires": {
        "brand", "tire_width", "tire_profile", "tire_diameter", "season", "load_index",
        "speed_index", "runflat", "studded", "weight", "image_url",
    },
    "batteries": {
        "brand", "capacity_ah", "voltage_v", "start_current_a", "polarity", "battery_type",
        "dimensions", "terminal_type", "weight", "features", "length", "width", "height", "image_url",
    },
    "filters": {
        "brand", "filter_type", "compatible_brand", "compatible_model", "oem_number",
        "additional_information", "image_url",
    },
}


def table_exists(cur, schema: str, table: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
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
        WHERE table_schema = %s AND table_name = %s
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


def clean_text_value(value) -> str | None:
    if value is None:
        return None
    text = str(python_value(value)).strip()
    return text if text and text.lower() not in {"nan", "none", "null"} else None


def iter_cursor_batches(cur, size: int = 10_000):
    while True:
        batch = cur.fetchmany(size)
        if not batch:
            break
        yield batch


def ensure_base_constraints(cur, match_schema: str) -> None:
    cur.execute(
        """
        DO $$
        DECLARE
            s text := %s;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = format('%%I.skus', s)::regclass AND contype = 'p'
            ) THEN
                BEGIN
                    EXECUTE format('ALTER TABLE %%I.skus ADD CONSTRAINT skus_pkey PRIMARY KEY (id)', s);
                EXCEPTION
                    WHEN duplicate_object OR invalid_table_definition THEN
                        NULL;
                END;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = format('%%I.categories', s)::regclass AND contype = 'p'
            ) THEN
                BEGIN
                    EXECUTE format('ALTER TABLE %%I.categories ADD CONSTRAINT categories_pkey PRIMARY KEY (category_id)', s);
                EXCEPTION
                    WHEN duplicate_object OR invalid_table_definition THEN
                        NULL;
                END;
            END IF;
        END $$;
        """,
        (match_schema,),
    )


def ensure_attribute_dictionary(cur, match_schema: str) -> dict[str, int]:
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {q_ident(match_schema)}")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {q_ident(match_schema)}.attributes (
            id smallint PRIMARY KEY,
            name text NOT NULL UNIQUE,
            unit text,
            status text NOT NULL DEFAULT 'active'
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {q_ident(match_schema)}.attribute_groups (
            id smallint PRIMARY KEY,
            name text NOT NULL UNIQUE,
            status text NOT NULL DEFAULT 'active'
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {q_ident(match_schema)}.attributes_attribute_groups (
            attribute_group_id smallint NOT NULL REFERENCES {q_ident(match_schema)}.attribute_groups(id),
            attribute_group text NOT NULL,
            attribute_id smallint NOT NULL REFERENCES {q_ident(match_schema)}.attributes(id),
            attribute text NOT NULL,
            PRIMARY KEY (attribute_group_id, attribute_id)
        )
        """
    )

    execute_values(
        cur,
        f"""
        INSERT INTO {q_ident(match_schema)}.attribute_groups (id, name, status)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, status = EXCLUDED.status
        """,
        [(group_id, name, "active") for group_id, name in ATTRIBUTE_GROUPS.items()],
    )

    attr_id_by_name = {name: idx for idx, (name, _unit, _group_id) in enumerate(ATTRIBUTES, 1)}
    execute_values(
        cur,
        f"""
        INSERT INTO {q_ident(match_schema)}.attributes (id, name, unit, status)
        VALUES %s
        ON CONFLICT (id) DO UPDATE
          SET name = EXCLUDED.name,
              unit = EXCLUDED.unit,
              status = EXCLUDED.status
        """,
        [(attr_id_by_name[name], name, unit, "active") for name, unit, _group_id in ATTRIBUTES],
    )

    execute_values(
        cur,
        f"""
        INSERT INTO {q_ident(match_schema)}.attributes_attribute_groups
            (attribute_group_id, attribute_group, attribute_id, attribute)
        VALUES %s
        ON CONFLICT (attribute_group_id, attribute_id) DO UPDATE
          SET attribute_group = EXCLUDED.attribute_group,
              attribute = EXCLUDED.attribute
        """,
        [
            (group_id, ATTRIBUTE_GROUPS[group_id], attr_id_by_name[name], name)
            for name, _unit, group_id in ATTRIBUTES
        ],
    )
    return attr_id_by_name


def ensure_category_attributes(cur, match_schema: str, attr_id_by_name: dict[str, int]) -> int:
    cur.execute(f"DROP TABLE IF EXISTS {q_ident(match_schema)}.category_attributes CASCADE")
    cur.execute(
        f"""
        CREATE TABLE {q_ident(match_schema)}.category_attributes (
            category_id bigint NOT NULL REFERENCES {q_ident(match_schema)}.categories(category_id),
            category text,
            attribute_group_id smallint REFERENCES {q_ident(match_schema)}.attribute_groups(id),
            attribute_group text,
            attribute_id smallint NOT NULL REFERENCES {q_ident(match_schema)}.attributes(id),
            attribute text,
            PRIMARY KEY (category_id, attribute_id)
        )
        """
    )
    rows = []
    cur.execute(
        f"""
        WITH RECURSIVE up AS (
            SELECT category_id, name, category_id AS anc, level, parent_category_id
            FROM {q_ident(match_schema)}.categories
            UNION ALL
            SELECT up.category_id, up.name, c.category_id AS anc, c.level, c.parent_category_id
            FROM up
            JOIN {q_ident(match_schema)}.categories c ON c.category_id = up.parent_category_id
        )
        SELECT DISTINCT category_id, name,
               CASE anc
                   WHEN 2 THEN 'oils'
                   WHEN 30 THEN 'tires'
                   WHEN 50 THEN 'batteries'
                   WHEN 60 THEN 'filters'
               END AS domain
        FROM up
        WHERE level = 2
        """
    )
    attr_group_by_name = {name: group_id for name, _unit, group_id in ATTRIBUTES}
    for category_id, category_name, domain in cur.fetchall():
        if not domain:
            continue
        for attribute in sorted(DOMAIN_ATTRIBUTES[domain]):
            attr_id = attr_id_by_name.get(attribute)
            group_id = attr_group_by_name.get(attribute)
            if not attr_id or not group_id:
                continue
            rows.append((category_id, category_name, group_id, ATTRIBUTE_GROUPS[group_id], attr_id, attribute))

    if rows:
        execute_values(
            cur,
            f"""
            INSERT INTO {q_ident(match_schema)}.category_attributes
                (category_id, category, attribute_group_id, attribute_group, attribute_id, attribute)
            VALUES %s
            """,
            rows,
            page_size=1000,
        )
    return len(rows)


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


def table_domain(table_name: str) -> str | None:
    for domain in ("oils", "tires", "batteries", "filters"):
        if domain in table_name:
            return domain
    return None


def build_sku_attribute_values(cur, clean_schema: str, match_schema: str, attr_id_by_name: dict[str, int]) -> int:
    cur.execute(f"DROP TABLE IF EXISTS {q_ident(match_schema)}.sku_attribute_values")
    cur.execute(
        f"""
        CREATE TABLE {q_ident(match_schema)}.sku_attribute_values (
            sku_id text NOT NULL REFERENCES {q_ident(match_schema)}.skus(id),
            attribute_id smallint NOT NULL REFERENCES {q_ident(match_schema)}.attributes(id),
            attribute text,
            value text,
            PRIMARY KEY (sku_id, attribute_id)
        )
        """
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_sav_attribute_id ON {q_ident(match_schema)}.sku_attribute_values (attribute_id)")

    sku_map = load_sku_map(cur, match_schema)
    values: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)

    for table in list_clean_tables(cur, clean_schema):
        domain = table_domain(table)
        if not domain:
            continue
        columns = table_columns(cur, clean_schema, table)
        if not {"source", "source_product_id"} <= columns:
            continue
        attr_columns = sorted(DOMAIN_ATTRIBUTES[domain] & columns)
        if not attr_columns:
            continue
        selected = ["source", "source_product_id", *attr_columns]
        cur.execute(
            f"SELECT {', '.join(q_ident(column) for column in selected)} "
            f"FROM {q_ident(clean_schema)}.{q_ident(table)}"
        )
        result_columns = [desc[0] for desc in cur.description]
        for batch in iter_cursor_batches(cur):
            for raw_row in batch:
                row = dict(zip(result_columns, raw_row))
                sku_id = sku_map.get((str(row["source"]), str(row["source_product_id"])))
                if not sku_id:
                    continue
                for attribute in attr_columns:
                    value = clean_text_value(row.get(attribute))
                    if value:
                        values[(sku_id, attribute)][value] += 1

    rows = []
    for (sku_id, attribute), counter in values.items():
        attr_id = attr_id_by_name.get(attribute)
        if attr_id:
            rows.append((sku_id, attr_id, attribute, counter.most_common(1)[0][0]))

    if rows:
        execute_values(
            cur,
            f"""
            INSERT INTO {q_ident(match_schema)}.sku_attribute_values
                (sku_id, attribute_id, attribute, value)
            VALUES %s
            ON CONFLICT (sku_id, attribute_id) DO UPDATE
              SET attribute = EXCLUDED.attribute,
                  value = EXCLUDED.value
            """,
            rows,
            page_size=5000,
        )
    return len(rows)


def build_matching_attributes(clean_schema: str, match_schema: str, config: PostgresConfig | None = None) -> None:
    with connect(config or config_from_env()) as conn:
        with conn.cursor() as cur:
            for table in ("categories", "skus", "sku_source_mapping"):
                if not table_exists(cur, match_schema, table):
                    raise RuntimeError(f"Required table {match_schema}.{table} does not exist.")
            ensure_base_constraints(cur, match_schema)
            attr_id_by_name = ensure_attribute_dictionary(cur, match_schema)
            category_attribute_count = ensure_category_attributes(cur, match_schema, attr_id_by_name)
            sku_attribute_value_count = build_sku_attribute_values(cur, clean_schema, match_schema, attr_id_by_name)
            print(f"attributes rows: {len(attr_id_by_name)}", flush=True)
            print(f"category_attributes rows: {category_attribute_count}", flush=True)
            print(f"sku_attribute_values rows: {sku_attribute_value_count}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build matching attribute dictionary and SKU attribute values.")
    parser.add_argument("--clean-schema", default=os.environ.get("CLEAN_SCHEMA", "cleanned"))
    parser.add_argument("--match-schema", default=os.environ.get("MATCH_SCHEMA", "matching"))
    args = parser.parse_args()
    build_matching_attributes(args.clean_schema, args.match_schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
