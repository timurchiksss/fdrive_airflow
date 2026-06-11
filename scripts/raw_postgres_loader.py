#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg2


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


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


def q_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def transliterate(value: str) -> str:
    return "".join(CYRILLIC.get(ch, ch) for ch in value.lower())


def safe_column_name(original: str, position: int, used: set[str]) -> str:
    base = transliterate(original)
    base = re.sub(r"[^a-z0-9]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_") or "column"
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


def build_column_map(header: list[str]) -> list[tuple[str, str]]:
    used: set[str] = set()
    return [(source, safe_column_name(source, i, used)) for i, source in enumerate(header, 1)]


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        try:
            return [column for column in next(csv.reader(file)) if column]
        except StopIteration:
            return []


def resolve_files(data_dir: Path, files: list[str], *, strict: bool) -> list[Path]:
    resolved = []
    for file_name in files:
        path = data_dir / file_name
        if path.exists():
            resolved.append(path)
    if strict and not resolved:
        raise FileNotFoundError(
            f"None of the expected files exists under {data_dir}: {', '.join(files)}"
        )
    return resolved


def validate_headers(paths: list[Path]) -> list[str]:
    first_header = read_header(paths[0])
    if not first_header:
        raise ValueError(f"{paths[0]} has an empty CSV header.")
    for path in paths[1:]:
        header = read_header(path)
        if not header:
            raise ValueError(f"{path} has an empty CSV header.")
        if header != first_header:
            raise ValueError(
                f"{path} has a different header than {paths[0]}; "
                "load it into a separate raw table or align the CSV schemas first."
            )
    return first_header


def skip_empty_header_files(paths: list[Path], table: str) -> list[Path]:
    loadable = []
    for path in paths:
        if read_header(path):
            loadable.append(path)
        else:
            print(f"skip {table}: {path} has no CSV header", flush=True)
    return loadable


def connect(config: PostgresConfig):
    return psycopg2.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        dbname=config.database,
    )


def ensure_database_exists(config: PostgresConfig, maintenance_database: str = "postgres") -> None:
    maintenance_config = PostgresConfig(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=maintenance_database,
    )
    conn = connect(maintenance_config)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (config.database,))
            if cur.fetchone():
                return
            cur.execute(f"CREATE DATABASE {q_ident(config.database)}")
            print(f"created database {config.database}", flush=True)
    finally:
        conn.close()


def ensure_metadata(cur, schema: str) -> None:
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {q_ident(schema)}")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {q_ident(schema)}._column_map (
            table_name text NOT NULL,
            column_position integer NOT NULL,
            db_column_name text NOT NULL,
            source_column_name text NOT NULL,
            PRIMARY KEY (table_name, column_position)
        )
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {q_ident(schema)}._load_files (
            load_id text NOT NULL,
            table_name text NOT NULL,
            source_file text NOT NULL,
            loaded_at timestamptz NOT NULL DEFAULT now(),
            row_count bigint,
            PRIMARY KEY (load_id, table_name, source_file)
        )
        """
    )


def column_defs(columns: list[tuple[str, str]]) -> list[str]:
    return [f"{q_ident(db_col)} text" for _, db_col in columns]


def audit_column_defs() -> list[str]:
    return [
        "source_file text NOT NULL",
        "loaded_at timestamptz NOT NULL DEFAULT now()",
        "load_id text NOT NULL",
    ]


def create_empty_table(cur, schema: str, table: str, columns: list[tuple[str, str]]) -> None:
    definitions = ", ".join(column_defs(columns) + audit_column_defs())
    cur.execute(f"CREATE TABLE IF NOT EXISTS {q_ident(schema)}.{q_ident(table)} ({definitions})")
    ensure_table_columns(cur, schema, table, columns)


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


def ensure_table_columns(cur, schema: str, table: str, columns: list[tuple[str, str]]) -> None:
    existing = table_columns(cur, schema, table)
    for definition in column_defs(columns) + audit_column_defs():
        column_name = definition.split(" ", 1)[0].strip('"').replace('""', '"')
        if column_name not in existing:
            cur.execute(f"ALTER TABLE {q_ident(schema)}.{q_ident(table)} ADD COLUMN {definition}")
            existing.add(column_name)


def canonical_files(data_dir: Path, tables: set[str] | None = None) -> list[Path]:
    normalized_dir = data_dir / "normalized"
    if not normalized_dir.exists():
        return []
    return sorted(
        path
        for path in normalized_dir.glob("*.csv")
        if read_header(path) and (tables is None or path.stem in tables)
    )


def canonical_table_name(path: Path) -> str:
    return path.stem


def initialize_database(config: PostgresConfig, schema: str, data_dir: Path | None = None) -> None:
    with connect(config) as conn:
        with conn.cursor() as cur:
            ensure_metadata(cur, schema)
            if data_dir is None:
                return

            keep_tables: set[str] = set()
            for path in canonical_files(data_dir):
                table = canonical_table_name(path)
                header = read_header(path)
                create_empty_table(cur, schema, table, [(column, column) for column in header])
                keep_tables.add(table)
            if keep_tables:
                print(
                    f"initialized {len(keep_tables)} raw tables in append mode; "
                    "existing non-canonical tables were left untouched",
                    flush=True,
                )


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return max(sum(1 for _ in file) - 1, 0)


def load_table(cur, schema: str, table: str, paths: list[Path], columns: list[tuple[str, str]], load_id: str) -> None:
    db_cols = [db_col for _, db_col in columns]
    col_defs = ", ".join(column_defs(columns))
    create_empty_table(cur, schema, table, columns)
    cur.execute(f"DELETE FROM {q_ident(schema)}.{q_ident(table)} WHERE load_id = %s", (load_id,))

    copy_cols = ", ".join(q_ident(col) for col in db_cols)
    for path in paths:
        staging_table = f"_{table}_staging_{hashlib.sha1(str(path).encode()).hexdigest()[:12]}"
        cur.execute(f"CREATE TEMP TABLE {q_ident(staging_table)} ({col_defs}) ON COMMIT DROP")
        copy_sql = (
            f"COPY {q_ident(staging_table)} ({copy_cols}) "
            "FROM STDIN WITH (FORMAT csv, HEADER true)"
        )
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            cur.copy_expert(copy_sql, file)
        cur.execute(
            f"""
            INSERT INTO {q_ident(schema)}.{q_ident(table)}
                ({copy_cols}, source_file, load_id)
            SELECT
                {copy_cols}, %s, %s
            FROM {q_ident(staging_table)}
            """,
            (str(path), load_id),
        )
        cur.execute(f"DROP TABLE {q_ident(staging_table)}")

    cur.execute(f"DELETE FROM {q_ident(schema)}._column_map WHERE table_name = %s", (table,))
    cur.executemany(
        f"""
        INSERT INTO {q_ident(schema)}._column_map
            (table_name, column_position, db_column_name, source_column_name)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (table_name, column_position) DO UPDATE
        SET db_column_name = EXCLUDED.db_column_name,
            source_column_name = EXCLUDED.source_column_name
        """,
        [(table, i, db_col, source_col) for i, (source_col, db_col) in enumerate(columns, 1)],
    )

    cur.execute(f"DELETE FROM {q_ident(schema)}._load_files WHERE load_id = %s AND table_name = %s", (load_id, table))
    cur.executemany(
        f"""
        INSERT INTO {q_ident(schema)}._load_files
            (load_id, table_name, source_file, row_count)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (load_id, table_name, source_file) DO UPDATE
        SET row_count = EXCLUDED.row_count,
            loaded_at = now()
        """,
        [(load_id, table, str(path), count_csv_rows(path)) for path in paths],
    )


def load_canonical_tables(
    cur,
    data_dir: Path,
    schema: str,
    load_id: str,
    tables: set[str] | None = None,
) -> set[str]:
    paths = canonical_files(data_dir, tables=tables)
    if not paths:
        print(f"skip canonical tables: {data_dir / 'normalized'} has no loadable CSV files")
        return set()

    loaded_tables = set()
    for path in paths:
        table = canonical_table_name(path)
        header = read_header(path)
        columns = [(column, column) for column in header]
        print(f"loading canonical file -> {schema}.{table}", flush=True)
        load_table(cur, schema, table, [path], columns, load_id)
        loaded_tables.add(table)
    return loaded_tables


def load_csvs(
    data_dir: Path,
    schema: str,
    config: PostgresConfig,
    *,
    load_id: str | None = None,
    strict: bool = False,
    tables: set[str] | None = None,
    create_database: bool = False,
    maintenance_database: str = "postgres",
) -> str:
    load_id = load_id or str(uuid.uuid4())
    if create_database:
        ensure_database_exists(config, maintenance_database=maintenance_database)

    if strict and tables:
        available = {path.stem for path in canonical_files(data_dir, tables=tables)}
        missing = sorted(tables - available)
        if missing:
            raise FileNotFoundError(
                f"Missing normalized CSV files for tables: {', '.join(missing)}"
            )

    with connect(config) as conn:
        with conn.cursor() as cur:
            ensure_metadata(cur, schema)
            loaded_tables = load_canonical_tables(cur, data_dir, schema, load_id, tables=tables)
            if loaded_tables:
                print(
                    f"loaded {len(loaded_tables)} raw tables in append mode; "
                    "obsolete raw tables were left untouched",
                    flush=True,
                )

    return load_id


def config_from_env() -> PostgresConfig:
    return PostgresConfig(
        host=os.environ.get("RAW_PGHOST") or os.environ.get("PGHOST", "postgres"),
        port=int(os.environ.get("RAW_PGPORT") or os.environ.get("PGPORT", "5432")),
        user=os.environ.get("RAW_PGUSER") or os.environ.get("PGUSER", "airflow"),
        password=os.environ.get("RAW_PGPASSWORD") or os.environ.get("PGPASSWORD", "airflow"),
        database=os.environ.get("RAW_PGDATABASE") or os.environ.get("PGDATABASE", "airflow"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Load parser CSV files directly into Postgres raw schema.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--schema", default=os.environ.get("RAW_SCHEMA", "raw"))
    parser.add_argument("--load-id", default="")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    load_id = load_csvs(
        Path(args.data_dir),
        args.schema,
        config_from_env(),
        load_id=args.load_id or None,
        strict=args.strict,
    )
    print(f"done. load_id={load_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
