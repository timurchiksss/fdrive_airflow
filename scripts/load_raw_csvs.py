#!/usr/bin/env python3
import argparse
import csv
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


LOAD_PLAN = {
    "carcity_products": ["carcity_products.csv"],
    "pitstopshop_products": ["pitstopshop_products.csv"],
    "price_history": ["carcity_price_history.csv", "pitstopshop_price_history.csv"],
    "quality_gaps": ["carcity_quality_gaps.csv", "pitstopshop_quality_gaps.csv"],
    "satu_tires": ["satu/satu_tires.csv"],
    "satu_oils": ["satu/satu_oils.csv"],
    "satu_filters": ["satu/satu_filters.csv"],
    "satu_batteries": ["satu/satu_batteries.csv"],
    "forte_market_tires": ["forte_market/forte_tires.csv"],
    "forte_market_oils": ["forte_market/forte_oils.csv"],
    "forte_market_filters": ["forte_market/forte_filters.csv"],
    "forte_market_batteries": ["forte_market/forte_batteries.csv"],
    "fdrive_tyres": ["fdrive_tyres_almaty_full.csv"],
    "fdrive_oils": ["fdrive_masla_i_zhidkosti_full.csv"],
    "almatyres_products": ["almatyres_products.csv"],
}


CYRILLIC = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def q_ident(name):
    return '"' + name.replace('"', '""') + '"'


def q_literal(value):
    return "'" + value.replace("'", "''") + "'"


def transliterate(value):
    return "".join(CYRILLIC.get(ch, ch) for ch in value.lower())


def safe_column_name(original, position, used):
    base = transliterate(original)
    base = re.sub(r"[^a-z0-9]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    if not base:
        base = "column"

    # PostgreSQL identifiers are limited to 63 bytes. Keep a deterministic
    # prefix so large Cyrillic source headers remain queryable and unique.
    base = f"c{position:03d}_{base}"
    digest = hashlib.sha1(original.encode("utf-8")).hexdigest()[:8]
    if len(base.encode("utf-8")) > 55:
        base = base.encode("utf-8")[:46].decode("utf-8", errors="ignore").rstrip("_")
        base = f"{base}_{digest}"

    candidate = base
    suffix = 2
    while candidate in used:
        tail = f"_{suffix}"
        candidate = base[: 63 - len(tail)] + tail
        suffix += 1
    used.add(candidate)
    return candidate


def read_header(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        return next(reader)


def run_psql(sql, env):
    cmd = [
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        env["PGHOST"],
        "-p",
        env["PGPORT"],
        "-U",
        env["PGUSER"],
        "-d",
        env["PGDATABASE"],
    ]
    return subprocess.run(cmd, input=sql, text=True, check=True)


def build_column_map(header):
    used = set()
    return [(original, safe_column_name(original, i, used)) for i, original in enumerate(header, 1)]


def create_metadata(schema, env):
    sql = f"""
CREATE SCHEMA IF NOT EXISTS {q_ident(schema)};
CREATE TABLE IF NOT EXISTS {q_ident(schema)}._column_map (
    table_name text NOT NULL,
    column_position integer NOT NULL,
    db_column_name text NOT NULL,
    source_column_name text NOT NULL,
    PRIMARY KEY (table_name, column_position)
);
CREATE TABLE IF NOT EXISTS {q_ident(schema)}._load_files (
    load_id text NOT NULL,
    table_name text NOT NULL,
    source_file text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    row_count bigint,
    PRIMARY KEY (load_id, table_name, source_file)
);
"""
    run_psql(sql, env)


def create_table(schema, table, columns, env, replace):
    if replace:
        run_psql(f"DROP TABLE IF EXISTS {q_ident(schema)}.{q_ident(table)} CASCADE;\n", env)

    defs = [f"{q_ident(db_col)} text" for _, db_col in columns]
    defs.extend(
        [
            "source_file text NOT NULL",
            "loaded_at timestamptz NOT NULL DEFAULT now()",
            "load_id text NOT NULL",
        ]
    )
    create_sql = f"""
CREATE TABLE IF NOT EXISTS {q_ident(schema)}.{q_ident(table)} (
    {", ".join(defs)}
);
DELETE FROM {q_ident(schema)}._column_map WHERE table_name = {q_literal(table)};
"""
    values = []
    for i, (source_col, db_col) in enumerate(columns, 1):
        values.append(
            f"({q_literal(table)}, {i}, {q_literal(db_col)}, {q_literal(source_col)})"
        )
    create_sql += f"""
INSERT INTO {q_ident(schema)}._column_map
    (table_name, column_position, db_column_name, source_column_name)
VALUES
    {", ".join(values)}
ON CONFLICT (table_name, column_position) DO UPDATE
SET db_column_name = EXCLUDED.db_column_name,
    source_column_name = EXCLUDED.source_column_name;
"""
    run_psql(create_sql, env)


def load_file(schema, table, csv_path, columns, load_id, env):
    temp_table = "tmp_" + hashlib.sha1(f"{table}:{csv_path}".encode()).hexdigest()[:16]
    db_cols = [db_col for _, db_col in columns]
    col_defs = ", ".join(f"{q_ident(col)} text" for col in db_cols)
    col_list = ", ".join(q_ident(col) for col in db_cols)
    insert_cols = f"{col_list}, source_file, load_id"
    select_cols = f"{col_list}, {q_literal(csv_path.name)}, {q_literal(load_id)}"

    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
        f.write(
            f"""
CREATE TEMP TABLE {q_ident(temp_table)} ({col_defs});
\\copy {q_ident(temp_table)} ({col_list}) FROM {q_literal(str(csv_path.resolve()))} WITH (FORMAT csv, HEADER true)
INSERT INTO {q_ident(schema)}.{q_ident(table)} ({insert_cols})
SELECT {select_cols}
FROM {q_ident(temp_table)};
INSERT INTO {q_ident(schema)}._load_files
    (load_id, table_name, source_file, row_count)
SELECT {q_literal(load_id)}, {q_literal(table)}, {q_literal(csv_path.name)}, count(*)
FROM {q_ident(temp_table)}
ON CONFLICT (load_id, table_name, source_file) DO UPDATE
SET row_count = EXCLUDED.row_count,
    loaded_at = now();
"""
        )
        sql_path = f.name

    cmd = [
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        env["PGHOST"],
        "-p",
        env["PGPORT"],
        "-U",
        env["PGUSER"],
        "-d",
        env["PGDATABASE"],
        "-f",
        sql_path,
    ]
    try:
        subprocess.run(cmd, check=True)
    finally:
        Path(sql_path).unlink(missing_ok=True)


def validate_headers(data_dir, files):
    first_header = read_header(data_dir / files[0])
    for file_name in files[1:]:
        header = read_header(data_dir / file_name)
        if header != first_header:
            raise ValueError(
                f"{file_name} has a different header than {files[0]}; "
                "load it into a separate raw table or align the schema first."
            )
    return first_header


def main():
    parser = argparse.ArgumentParser(description="Load selected CSV files into Postgres raw schema.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--schema", default="raw")
    parser.add_argument("--replace", action="store_true", help="drop and recreate target raw tables before loading")
    parser.add_argument("--load-id", default=str(uuid.uuid4()))
    args = parser.parse_args()

    env = {
        "PGHOST": os.environ.get("PGHOST", "localhost"),
        "PGPORT": os.environ.get("PGPORT", "5432"),
        "PGUSER": os.environ.get("PGUSER", os.environ.get("USER", "postgres")),
        "PGDATABASE": os.environ.get("PGDATABASE", "fdrive_raw"),
    }
    if os.environ.get("PGPASSWORD"):
        os.environ["PGPASSWORD"] = os.environ["PGPASSWORD"]

    data_dir = Path(args.data_dir)
    create_metadata(args.schema, env)

    for table, files in LOAD_PLAN.items():
        for file_name in files:
            if not (data_dir / file_name).exists():
                raise FileNotFoundError(data_dir / file_name)

        header = validate_headers(data_dir, files)
        columns = build_column_map(header)
        create_table(args.schema, table, columns, env, args.replace)

        for file_name in files:
            csv_path = data_dir / file_name
            print(f"loading {csv_path} -> {args.schema}.{table}", flush=True)
            load_file(args.schema, table, csv_path, columns, args.load_id, env)

    print(f"done. load_id={args.load_id}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"psql failed with exit code {exc.returncode}", file=sys.stderr)
        sys.exit(exc.returncode)
