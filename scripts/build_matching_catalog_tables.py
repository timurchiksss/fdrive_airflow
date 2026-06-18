#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict
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

ATTRIBUTE_GROUPS = {
    1: "Основные",
    2: "Технические характеристики",
    3: "Размеры",
    4: "Совместимость",
    5: "Дополнительно",
}

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

TABLE_DOMAINS = {
    "oils": "oils",
    "tires": "tires",
    "batteries": "batteries",
    "filters": "filters",
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
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def clean_text_value(value) -> str | None:
    if value is None:
        return None
    value = python_value(value)
    text = str(value).strip()
    return text if text and text.lower() not in {"nan", "none", "null"} else None


def ensure_attribute_tables(cur, match_schema: str) -> dict[str, int]:
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

    group_rows = [(group_id, name, "active") for group_id, name in ATTRIBUTE_GROUPS.items()]
    execute_values(
        cur,
        f"""
        INSERT INTO {q_ident(match_schema)}.attribute_groups (id, name, status)
        VALUES %s
        ON CONFLICT (id) DO UPDATE
          SET name = EXCLUDED.name, status = EXCLUDED.status
        """,
        group_rows,
    )

    attr_rows = [(idx, name, unit, "active") for idx, (name, unit, _) in enumerate(ATTRIBUTES, 1)]
    execute_values(
        cur,
        f"""
        INSERT INTO {q_ident(match_schema)}.attributes (id, name, unit, status)
        VALUES %s
        ON CONFLICT (id) DO UPDATE
          SET name = EXCLUDED.name, unit = EXCLUDED.unit, status = EXCLUDED.status
        """,
        attr_rows,
    )

    attr_id_by_name = {name: idx for idx, (name, _, _) in enumerate(ATTRIBUTES, 1)}
    group_rows = [
        (group_id, ATTRIBUTE_GROUPS[group_id], attr_id_by_name[name], name)
        for name, _, group_id in ATTRIBUTES
    ]
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
        group_rows,
    )
    return attr_id_by_name


def ensure_category_attributes(cur, match_schema: str, attr_id_by_name: dict[str, int]) -> None:
    cur.execute(f"DROP TABLE IF EXISTS {q_ident(match_schema)}.category_attributes CASCADE")
    cur.execute(
        f"""
        CREATE TABLE {q_ident(match_schema)}.category_attributes (
            category_id bigint NOT NULL,
            category text,
            attribute_group_id smallint,
            attribute_group text,
            attribute_id smallint NOT NULL,
            attribute text,
            PRIMARY KEY (category_id, attribute_id)
        )
        """
    )

    domain_roots = {"oils": 2, "tires": 30, "batteries": 50, "filters": 60}
    rows = []
    cur.execute(f"SELECT category_id, parent_category_id, level, name FROM {q_ident(match_schema)}.categories")
    categories = {
        int(category_id): {
            "parent": int(parent) if parent is not None else None,
            "level": int(level),
            "name": name,
        }
        for category_id, parent, level, name in cur.fetchall()
    }

    for category_id, category in categories.items():
        node = category
        domain = None
        while node:
            for domain_name, root_id in domain_roots.items():
                if category_id == root_id or node.get("parent") == root_id or (node["level"] == 2 and category_id == root_id):
                    domain = domain_name
                    break
            if domain:
                break
            parent_id = node.get("parent")
            node = categories.get(parent_id) if parent_id else None
        if not domain:
            continue
        for attribute in sorted(DOMAIN_ATTRIBUTES[domain]):
            attr_id = attr_id_by_name.get(attribute)
            if not attr_id:
                continue
            group_id = next(group for name, _, group in ATTRIBUTES if name == attribute)
            rows.append((category_id, category["name"], group_id, ATTRIBUTE_GROUPS[group_id], attr_id, attribute))

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


def ensure_constraints(cur, match_schema: str) -> None:
    cur.execute(
        """
        DO $$
        DECLARE
            s text := %s;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = format('%%I.categories', s)::regclass
                  AND conname = 'categories_pkey'
            ) THEN
                EXECUTE format('ALTER TABLE %%I.categories ADD CONSTRAINT categories_pkey PRIMARY KEY (category_id)', s);
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = s AND table_name = 'categories'
                  AND column_name = 'parent_category_id'
                  AND data_type <> 'bigint'
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %%I.categories ALTER COLUMN parent_category_id TYPE bigint USING parent_category_id::bigint',
                    s
                );
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = format('%%I.categories', s)::regclass
                  AND conname = 'categories_parent_fkey'
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %%I.categories ADD CONSTRAINT categories_parent_fkey FOREIGN KEY (parent_category_id) REFERENCES %%I.categories(category_id)',
                    s, s
                );
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = format('%%I.skus', s)::regclass
                  AND conname = 'skus_pkey'
            ) THEN
                EXECUTE format('ALTER TABLE %%I.skus ADD CONSTRAINT skus_pkey PRIMARY KEY (id)', s);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = format('%%I.skus', s)::regclass
                  AND conname = 'skus_category_id_fkey'
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %%I.skus ADD CONSTRAINT skus_category_id_fkey FOREIGN KEY (category_id) REFERENCES %%I.categories(category_id)',
                    s, s
                );
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = format('%%I.sku_source_mapping', s)::regclass
                  AND conname = 'sku_source_mapping_sku_id_fkey'
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %%I.sku_source_mapping ADD CONSTRAINT sku_source_mapping_sku_id_fkey FOREIGN KEY (sku_id) REFERENCES %%I.skus(id)',
                    s, s
                );
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = format('%%I.category_attributes', s)::regclass
                  AND conname = 'category_attributes_category_fkey'
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %%I.category_attributes ADD CONSTRAINT category_attributes_category_fkey FOREIGN KEY (category_id) REFERENCES %%I.categories(category_id)',
                    s, s
                );
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = format('%%I.category_attributes', s)::regclass
                  AND conname = 'category_attributes_group_fkey'
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %%I.category_attributes ADD CONSTRAINT category_attributes_group_fkey FOREIGN KEY (attribute_group_id) REFERENCES %%I.attribute_groups(id)',
                    s, s
                );
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = format('%%I.category_attributes', s)::regclass
                  AND conname = 'category_attributes_attribute_id_fkey'
            ) THEN
                EXECUTE format(
                    'ALTER TABLE %%I.category_attributes ADD CONSTRAINT category_attributes_attribute_id_fkey FOREIGN KEY (attribute_id) REFERENCES %%I.attributes(id)',
                    s, s
                );
            END IF;
        END $$;
        """,
        (match_schema,),
    )


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


def build_sku_attribute_values(cur, clean_schema: str, match_schema: str, attr_id_by_name: dict[str, int]) -> None:
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
    clean_tables = list_clean_tables(cur, clean_schema)
    allowed = {name for domain_attrs in DOMAIN_ATTRIBUTES.values() for name in domain_attrs}

    for table in clean_tables:
        domain = next((domain for token, domain in TABLE_DOMAINS.items() if token in table), None)
        if not domain:
            continue
        columns = table_columns(cur, clean_schema, table)
        attr_columns = sorted((DOMAIN_ATTRIBUTES[domain] | {"brand"}) & allowed & columns)
        required = {"source", "source_product_id"} | set(attr_columns)
        if not {"source", "source_product_id"} <= columns or not attr_columns:
            continue
        select_sql = ", ".join(q_ident(column) for column in sorted(required))
        cur.execute(f"SELECT {select_sql} FROM {q_ident(clean_schema)}.{q_ident(table)}")
        result_columns = [desc[0] for desc in cur.description]
        for raw_row in cur.fetchall():
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
        if not attr_id:
            continue
        value = counter.most_common(1)[0][0]
        rows.append((sku_id, attr_id, attribute, value))

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
    print(f"sku_attribute_values rows: {len(rows)}", flush=True)


def build_sku_price_history(cur, clean_schema: str, match_schema: str) -> None:
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
            loaded_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_sph UNIQUE (source, source_product_id, captured_at)
        )
        """
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS ix_sph_sku ON {q_ident(match_schema)}.sku_price_history (sku_id)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS ix_sph_date ON {q_ident(match_schema)}.sku_price_history (price_date)")

    sku_map = load_sku_map(cur, match_schema)
    rows = []
    for table in list_clean_tables(cur, clean_schema):
        columns = table_columns(cur, clean_schema, table)
        if not {"source", "source_product_id", "price"} <= columns:
            continue
        selectable = [
            column for column in (
                "source", "source_product_id", "city", "price", "old_price",
                "currency", "availability", "parsed_at", "loaded_at",
            )
            if column in columns
        ]
        cur.execute(
            f"SELECT {', '.join(q_ident(column) for column in selectable)} "
            f"FROM {q_ident(clean_schema)}.{q_ident(table)} WHERE price IS NOT NULL"
        )
        result_columns = [desc[0] for desc in cur.description]
        for raw_row in cur.fetchall():
            row = dict(zip(result_columns, raw_row))
            source = clean_text_value(row.get("source"))
            source_product_id = clean_text_value(row.get("source_product_id"))
            if not source or not source_product_id:
                continue
            captured_at = row.get("loaded_at") or datetime.now(timezone.utc)
            price = python_value(row.get("price"))
            old_price = python_value(row.get("old_price"))
            discount_price = price if old_price is not None and price is not None and old_price > price else None
            rows.append((
                captured_at,
                captured_at.date() if hasattr(captured_at, "date") else None,
                sku_map.get((source, source_product_id)),
                source,
                source_product_id,
                source,
                clean_text_value(row.get("city")),
                price,
                old_price,
                discount_price,
                clean_text_value(row.get("currency")),
                clean_text_value(row.get("availability")),
                row.get("parsed_at") if row.get("parsed_at") not in ("", None) else None,
            ))

    if rows:
        deduped_rows = {}
        for row in rows:
            deduped_rows[(row[3], row[4], row[0])] = row
        rows = list(deduped_rows.values())
        execute_values(
            cur,
            f"""
            INSERT INTO {q_ident(match_schema)}.sku_price_history
                (captured_at, price_date, sku_id, source, source_product_id, seller_name,
                 city, price, old_price, discount_price, currency, availability, parsed_at)
            VALUES %s
            ON CONFLICT (source, source_product_id, captured_at) DO UPDATE
              SET sku_id = EXCLUDED.sku_id,
                  price = EXCLUDED.price,
                  old_price = EXCLUDED.old_price,
                  discount_price = EXCLUDED.discount_price,
                  currency = EXCLUDED.currency,
                  availability = EXCLUDED.availability,
                  loaded_at = now()
            """,
            rows,
            page_size=5000,
        )
    print(f"sku_price_history upserted rows: {len(rows)}", flush=True)


def build_catalog_tables(clean_schema: str, match_schema: str, config: PostgresConfig | None = None) -> None:
    with connect(config or config_from_env()) as conn:
        with conn.cursor() as cur:
            for required in ("categories", "skus", "sku_source_mapping"):
                if not table_exists(cur, match_schema, required):
                    raise RuntimeError(f"Required table {match_schema}.{required} does not exist yet.")

            attr_id_by_name = ensure_attribute_tables(cur, match_schema)
            ensure_category_attributes(cur, match_schema, attr_id_by_name)
            ensure_constraints(cur, match_schema)
            build_sku_attribute_values(cur, clean_schema, match_schema, attr_id_by_name)
            build_sku_price_history(cur, clean_schema, match_schema)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build TЗ catalog tables in matching schema.")
    parser.add_argument("--clean-schema", default=os.environ.get("CLEAN_SCHEMA", "cleanned"))
    parser.add_argument("--match-schema", default=os.environ.get("MATCH_SCHEMA", "matching"))
    args = parser.parse_args()
    build_catalog_tables(args.clean_schema, args.match_schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
