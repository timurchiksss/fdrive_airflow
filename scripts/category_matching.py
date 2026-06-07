#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
import warnings
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values


warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy connectable.*")
warnings.filterwarnings("ignore", message="The behavior of DataFrame concatenation with empty or all-NA entries is deprecated.*")

MATCH_COLUMNS = [
    "match_run_id",
    "category",
    "sku_1",
    "sku_2",
    "source_1",
    "source_2",
    "name_1",
    "name_2",
    "group_key",
    "score",
    "confidence",
    "match_type",
    "created_at",
]


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


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


def q_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def list_tables(conn, schema: str) -> list[str]:
    with conn.cursor() as cur:
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


def table_columns(conn, schema: str, table: str) -> set[str]:
    with conn.cursor() as cur:
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


def select_expr(column: str, columns: set[str]) -> str:
    if column in columns:
        return q_ident(column)
    return f"NULL::text AS {q_ident(column)}"


def read_clean_catalog(conn, schema: str, *, latest_only: bool) -> pd.DataFrame:
    frames = []
    wanted = [
        "source",
        "source_product_id",
        "source_url",
        "category_group",
        "product_name",
        "normalized_name",
        "brand",
        "viscosity",
        "volume_liters",
        "oil_type",
        "tire_width",
        "tire_profile",
        "tire_diameter",
        "season",
        "model_name",
        "filter_type",
        "oem_number",
        "capacity_ah",
        "voltage_v",
        "battery_type",
        "loaded_at",
        "load_id",
        "cleaned_at",
    ]
    for table in list_tables(conn, schema):
        columns = table_columns(conn, schema, table)
        if "product_name" not in columns:
            continue
        category_hint = table_category(table)
        selects = [select_expr(column, columns) for column in wanted]
        selects.append(f"{sql_literal(table)} AS table_name")
        if category_hint:
            selects.append(f"{sql_literal(category_hint)} AS table_category")
        else:
            selects.append("NULL::text AS table_category")
        sql = f"SELECT {', '.join(selects)} FROM {q_ident(schema)}.{q_ident(table)}"
        frame = pd.read_sql_query(sql, conn)
        frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=wanted + ["table_name", "table_category", "category", "sku_id", "name_clean"])

    df = pd.concat(frames, ignore_index=True)
    category_group = df["category_group"].replace("", pd.NA)
    df["category"] = category_group.fillna(df["table_category"]).str.lower()
    df["category"] = df["category"].replace({"tires": "tyres"})
    df = df[df["category"].isin({"oils", "tyres", "filters", "batteries"})].copy()

    df["source"] = df["source"].replace("", pd.NA).fillna(df["table_name"])
    fallback_product_id = pd.Series(df.index.astype(str), index=df.index)
    df["source_product_id"] = df["source_product_id"].replace("", pd.NA).fillna(fallback_product_id)
    df["sku_id"] = df["source"].astype(str) + ":" + df["source_product_id"].astype(str)
    df["normalized_name"] = df["normalized_name"].fillna(df["product_name"])
    df["name_clean"] = df["normalized_name"].apply(clean_text)

    if latest_only and not df.empty:
        df["_loaded_at"] = pd.to_datetime(df["loaded_at"], errors="coerce", utc=True)
        df["_cleaned_at"] = pd.to_datetime(df["cleaned_at"], errors="coerce", utc=True)
        df = df.sort_values(["_loaded_at", "_cleaned_at"], na_position="first")
        df = df.drop_duplicates(["table_name", "source", "source_product_id"], keep="last")
        df = df.drop(columns=["_loaded_at", "_cleaned_at"])
    return df


def load_sentence_model(model_name: str):
    remove_profile_shadowing_paths()
    try:
        from sentence_transformers import SentenceTransformer
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on runtime image
        if exc.name != "sentence_transformers":
            raise
        raise SystemExit(
            "Missing dependency: sentence-transformers. "
            "Install requirements-airflow.txt and rebuild the Airflow Docker image."
        ) from exc
    return SentenceTransformer(model_name)


def remove_profile_shadowing_paths() -> None:
    """Avoid parsers/code for parser/profile.py shadowing stdlib profile."""
    shadow_paths = {
        path
        for path in sys.path
        if path and os.path.basename(path) == "code for parser"
    }
    if not shadow_paths:
        return

    sys.path[:] = [path for path in sys.path if path not in shadow_paths]
    module = sys.modules.get("profile")
    module_file = getattr(module, "__file__", "") if module else ""
    if module_file and any(module_file.startswith(path) for path in shadow_paths):
        del sys.modules["profile"]


def table_category(table: str) -> str | None:
    name = table.lower()
    if name.endswith("_oils"):
        return "oils"
    if name.endswith("_tires") or name.endswith("_tyres"):
        return "tyres"
    if name.endswith("_filters"):
        return "filters"
    if name.endswith("_batteries"):
        return "batteries"
    return None


def clean_text(text) -> str:
    if pd.isna(text):
        return ""
    text = str(text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_token(value) -> str:
    if pd.isna(value) or value == "":
        return "unknown"
    return str(value).lower().strip()


def clean_number(value, *, round_to_int: bool = True) -> str:
    if pd.isna(value):
        return "unknown"
    value = str(value).lower().strip()
    value = (
        value.replace("мм", "")
        .replace("л", "")
        .replace("l", "")
        .replace("литр", "")
        .replace("r", "")
        .replace('"', "")
        .replace("'", "")
        .replace(",", ".")
        .split(";")[0]
        .strip()
    )
    try:
        number = float(value)
    except ValueError:
        return "unknown"
    if round_to_int:
        return str(round(number))
    return f"{number:g}"


def clean_season(value) -> str:
    value = clean_token(value)
    if any(word in value for word in ["winter", "зимн", "шип"]):
        return "winter"
    if any(word in value for word in ["summer", "летн"]):
        return "summer"
    if any(word in value for word in ["all", "всесез"]):
        return "allseason"
    return value if value != "unknown" else "unknown"


def extract_oil_type(row: pd.Series) -> str:
    value = clean_token(row.get("oil_type"))
    if value != "unknown":
        return value
    name = row.get("name_clean", "")
    if "full synthetic" in name or "синтетическое" in name or "синтетик" in name:
        return "synthetic"
    if "полусинтетическое" in name or "semi" in name:
        return "semi"
    if "минеральное" in name or "mineral" in name:
        return "mineral"
    return "unknown"


def extract_tire_model(row: pd.Series) -> str:
    value = clean_token(row.get("model_name"))
    if value != "unknown":
        return value
    name = re.sub(r"\d+/\d+\s*r\d+", "", row.get("name_clean", ""))
    name = re.sub(r"\d+[a-z]$", "", name).strip()
    words = name.split()
    if len(words) > 1:
        return " ".join(words[1:3]).strip()
    return "unknown"


def clean_filter_type(value) -> str:
    value = clean_token(value)
    if any(word in value for word in ["воздушный", "air"]):
        return "air"
    if any(word in value for word in ["масляный", "oil"]):
        return "oil"
    if any(word in value for word in ["салонный", "cabin"]):
        return "cabin"
    if any(word in value for word in ["топливный", "fuel"]):
        return "fuel"
    if "трансмиссионный" in value:
        return "transmission"
    if "гидравлический" in value:
        return "hydraulic"
    return "unknown"


def clean_oem(value) -> str:
    if pd.isna(value):
        return "unknown"
    value = re.sub(r"[\s-]+", "", str(value).lower().strip())
    return value or "unknown"


def extract_article(name) -> str:
    matches = re.findall(r"[A-Z]{2,}[\d]+[A-Z\d]*", str(name))
    if matches:
        return matches[-1].lower()
    return "unknown"


def extract_battery_model(name) -> str:
    matches = re.findall(r"s\d+|silver|blue|black|asia|agm", str(name).lower())
    if matches:
        return matches[0]
    return "unknown"


def confidence(score: float) -> str:
    if score >= 0.9:
        return "HIGH"
    if score >= 0.75:
        return "MEDIUM"
    return "LOW"


def encode_similarity(model, names: list[str]) -> np.ndarray:
    embeddings = model.encode(names, batch_size=64, show_progress_bar=False)
    embeddings = np.asarray(embeddings, dtype=np.float32)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized = embeddings / norms
    return normalized @ normalized.T


def pair_key(sku_1: str, sku_2: str) -> tuple[str, str]:
    return tuple(sorted((sku_1, sku_2)))


def append_match(matches: list[dict], row_1, row_2, group_key: str, score: float, category: str, match_type: str) -> None:
    sku_1, sku_2 = str(row_1["sku_id"]), str(row_2["sku_id"])
    matches.append(
        {
            "category": category,
            "sku_1": sku_1,
            "sku_2": sku_2,
            "source_1": row_1["source"],
            "source_2": row_2["source"],
            "name_1": row_1["normalized_name"],
            "name_2": row_2["normalized_name"],
            "group_key": group_key,
            "score": round(float(score), 3),
            "confidence": confidence(float(score)),
            "match_type": match_type,
        }
    )


def semantic_group_matches(
    df: pd.DataFrame,
    model,
    *,
    category: str,
    threshold: float,
    match_type: str = "NLP",
    skip_unknown_group: bool = False,
    max_group_size: int | None = None,
) -> list[dict]:
    matches: list[dict] = []
    for group_key, group in df.groupby("group_key", dropna=False):
        if len(group) < 2 or group["source"].nunique() < 2:
            continue
        if skip_unknown_group and "unknown" in str(group_key):
            continue
        if max_group_size and len(group) > max_group_size:
            continue

        group = group.reset_index(drop=True)
        sim_matrix = encode_similarity(model, group["name_clean"].tolist())
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if group.iloc[i]["source"] == group.iloc[j]["source"]:
                    continue
                score = sim_matrix[i, j]
                if score >= threshold:
                    append_match(matches, group.iloc[i], group.iloc[j], str(group_key), score, category, match_type)
    return matches


def match_oils(df: pd.DataFrame, model, threshold: float) -> list[dict]:
    oils = df[df["category"] == "oils"].copy()
    oils["brand_clean"] = oils["brand"].apply(clean_token)
    oils["viscosity_clean"] = oils["viscosity"].apply(clean_token)
    oils["volume_clean"] = oils["volume_liters"].apply(clean_number)
    oils["oil_type_clean"] = oils.apply(extract_oil_type, axis=1)
    oils["group_key"] = (
        oils["brand_clean"] + "_" + oils["viscosity_clean"] + "_" + oils["volume_clean"] + "_" + oils["oil_type_clean"]
    )
    return semantic_group_matches(oils, model, category="oils", threshold=threshold, match_type="NLP")


def match_tyres(df: pd.DataFrame, model, threshold: float) -> list[dict]:
    tyres = df[df["category"] == "tyres"].copy()
    tyres["brand_clean"] = tyres["brand"].apply(clean_token)
    tyres["model_clean"] = tyres.apply(extract_tire_model, axis=1)
    tyres["width_clean"] = tyres["tire_width"].apply(clean_number)
    tyres["profile_clean"] = tyres["tire_profile"].apply(clean_number)
    tyres["diameter_clean"] = tyres["tire_diameter"].apply(clean_number)
    tyres["season_clean"] = tyres["season"].apply(clean_season)
    tyres["group_key"] = (
        tyres["brand_clean"]
        + "_"
        + tyres["model_clean"]
        + "_"
        + tyres["width_clean"]
        + "_"
        + tyres["profile_clean"]
        + "_"
        + tyres["diameter_clean"]
        + "_"
        + tyres["season_clean"]
    )
    return semantic_group_matches(
        tyres,
        model,
        category="tyres",
        threshold=threshold,
        match_type="NLP",
        skip_unknown_group=True,
    )


def match_filters(df: pd.DataFrame, model, threshold: float) -> list[dict]:
    filters = df[df["category"] == "filters"].copy()
    filters["brand_clean"] = filters["brand"].apply(clean_token)
    filters["filter_type_clean"] = filters["filter_type"].apply(clean_filter_type)
    filters["oem_clean"] = filters["oem_number"].apply(clean_oem)

    matches: list[dict] = []
    for oem, group in filters[filters["oem_clean"] != "unknown"].groupby("oem_clean"):
        if len(group) < 2 or group["source"].nunique() < 2:
            continue
        group = group.reset_index(drop=True)
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if group.iloc[i]["source"] != group.iloc[j]["source"]:
                    append_match(matches, group.iloc[i], group.iloc[j], oem, 1.0, "filters", "OEM")

    filters["article"] = filters["normalized_name"].apply(extract_article)
    filters["group_key"] = filters["brand_clean"] + "_" + filters["filter_type_clean"] + "_" + filters["article"]
    matches.extend(
        semantic_group_matches(
            filters,
            model,
            category="filters",
            threshold=threshold,
            match_type="NLP",
            skip_unknown_group=True,
            max_group_size=30,
        )
    )
    return matches


def match_batteries(df: pd.DataFrame, model, threshold: float) -> list[dict]:
    batteries = df[df["category"] == "batteries"].copy()
    batteries["brand_clean"] = batteries["brand"].apply(clean_token)
    batteries["capacity_clean"] = batteries["capacity_ah"].apply(clean_number)
    batteries["model_clean"] = batteries["normalized_name"].apply(extract_battery_model)
    batteries["group_key"] = batteries["brand_clean"] + "_" + batteries["model_clean"] + "_" + batteries["capacity_clean"]
    return semantic_group_matches(
        batteries,
        model,
        category="batteries",
        threshold=threshold,
        match_type="NLP",
        skip_unknown_group=True,
    )


def build_matches(df: pd.DataFrame, model_name: str, thresholds: dict[str, float]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=MATCH_COLUMNS)

    model = load_sentence_model(model_name)
    matches = []
    matches.extend(match_oils(df, model, thresholds["oils"]))
    matches.extend(match_tyres(df, model, thresholds["tyres"]))
    matches.extend(match_filters(df, model, thresholds["filters"]))
    matches.extend(match_batteries(df, model, thresholds["batteries"]))

    if not matches:
        return pd.DataFrame(columns=MATCH_COLUMNS)

    result = pd.DataFrame(matches)
    result[["_pair_1", "_pair_2"]] = result.apply(
        lambda row: pd.Series(pair_key(str(row["sku_1"]), str(row["sku_2"]))),
        axis=1,
    )
    result = result.sort_values(["category", "match_type", "score"], ascending=[True, True, False])
    result = result.drop_duplicates(["category", "_pair_1", "_pair_2"], keep="first")
    result = result.drop(columns=["_pair_1", "_pair_2"])
    return result


def ensure_output_table(cur, schema: str, table: str) -> None:
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {q_ident(schema)}")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {q_ident(schema)}.{q_ident(table)} (
            match_run_id text NOT NULL,
            category text NOT NULL,
            sku_1 text NOT NULL,
            sku_2 text NOT NULL,
            source_1 text,
            source_2 text,
            name_1 text,
            name_2 text,
            group_key text,
            score double precision,
            confidence text,
            match_type text,
            created_at timestamptz NOT NULL
        )
        """
    )


def write_matches(conn, df: pd.DataFrame, schema: str, table: str, match_run_id: str) -> None:
    created_at = datetime.now(timezone.utc)
    df = df.copy()
    df["match_run_id"] = match_run_id
    df["created_at"] = created_at
    df = df[MATCH_COLUMNS]

    with conn.cursor() as cur:
        ensure_output_table(cur, schema, table)
        cur.execute(
            f"DELETE FROM {q_ident(schema)}.{q_ident(table)} WHERE match_run_id = %s",
            (match_run_id,),
        )
        if not df.empty:
            rows = [tuple(None if pd.isna(value) else value for value in row) for row in df.itertuples(index=False, name=None)]
            execute_values(
                cur,
                f"""
                INSERT INTO {q_ident(schema)}.{q_ident(table)}
                    ({", ".join(q_ident(column) for column in MATCH_COLUMNS)})
                VALUES %s
                """,
                rows,
                page_size=1000,
            )
    conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Match product categories from cleanned Postgres schema.")
    parser.add_argument("--clean-schema", default=os.environ.get("CLEAN_SCHEMA", "cleanned"))
    parser.add_argument("--output-schema", default=os.environ.get("MATCH_SCHEMA", "matching"))
    parser.add_argument("--output-table", default=os.environ.get("MATCH_TABLE", "category_matches"))
    parser.add_argument("--match-run-id", default=str(uuid.uuid4()))
    parser.add_argument("--model", default=os.environ.get("MATCH_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"))
    parser.add_argument("--all-history", action="store_true", help="match every historical cleaned row instead of latest row per product")
    parser.add_argument("--csv", default="", help="optional CSV output path")
    parser.add_argument("--oil-threshold", type=float, default=0.70)
    parser.add_argument("--tyre-threshold", type=float, default=0.70)
    parser.add_argument("--filter-threshold", type=float, default=0.75)
    parser.add_argument("--battery-threshold", type=float, default=0.75)
    args = parser.parse_args()

    thresholds = {
        "oils": args.oil_threshold,
        "tyres": args.tyre_threshold,
        "filters": args.filter_threshold,
        "batteries": args.battery_threshold,
    }

    with connect(config_from_env()) as conn:
        catalog = read_clean_catalog(conn, args.clean_schema, latest_only=not args.all_history)
        print(f"loaded cleaned rows for matching: {len(catalog)}", flush=True)
        if not catalog.empty:
            print(catalog["category"].value_counts().to_string(), flush=True)

        matches = build_matches(catalog, args.model, thresholds)
        print(f"matches: {len(matches)}", flush=True)
        if not matches.empty:
            print(matches["category"].value_counts().to_string(), flush=True)
        write_matches(conn, matches, args.output_schema, args.output_table, args.match_run_id)

    if args.csv:
        matches.to_csv(args.csv, index=False)
        print(f"csv saved: {args.csv}", flush=True)
    print(f"done. match_run_id={args.match_run_id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
