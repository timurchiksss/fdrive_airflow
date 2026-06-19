from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.models import Variable
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator, get_current_context
from airflow.utils.trigger_rule import TriggerRule


PROJECT_ROOT = Path(os.environ.get("FDRIVE_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
DATA_DIR = PROJECT_ROOT / "data"
PARSERS_DIR = PROJECT_ROOT / "parsers"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
MATCHING_DIR = PROJECT_ROOT / "matching"

RAW_TABLES = {
    "fdrive_tires",
    "fdrive_oils",
    "fdrive_batteries",
    "carcity_tires",
    "carcity_oils",
    "carcity_filters",
    "carcity_batteries",
    "forte_market_tires",
    "forte_market_oils",
    "forte_market_filters",
    "forte_market_batteries",
    "satu_tires",
    "satu_oils",
    "satu_filters",
    "satu_batteries",
}

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from raw_postgres_loader import PostgresConfig, q_ident  # noqa: E402


def optional_config_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    value = Variable.get(name, default_var=None)
    if value not in (None, ""):
        return value
    return None


def config_value(name: str, default: str) -> str:
    return optional_config_value(name) or default


def required_config_value(name: str, *fallback_names: str) -> str:
    for candidate in (name, *fallback_names):
        value = optional_config_value(candidate)
        if value not in (None, ""):
            return value
    names = ", ".join((name, *fallback_names))
    raise RuntimeError(f"Required database config is missing. Set one of: {names}")


def env_flag(name: str, default: bool = False) -> bool:
    value = config_value(name, "true" if default else "false").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def run_cmd(args: list[str], extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    if extra_env:
        command_env.update(extra_env)
    command_env["PYTHONPATH"] = os.pathsep.join(
        str(path)
        for path in [PROJECT_ROOT, PARSERS_DIR, SCRIPTS_DIR, MATCHING_DIR, command_env.get("PYTHONPATH", "")]
        if str(path)
    )
    print(f"Running command: {' '.join(args)}", flush=True)
    process = subprocess.Popen(
        args,
        cwd=str(PROJECT_ROOT),
        env=command_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
    returncode = process.wait()
    if returncode:
        raise subprocess.CalledProcessError(returncode, args)
    return subprocess.CompletedProcess(args, returncode)


def current_load_id() -> str:
    try:
        context = get_current_context()
        dag_run = context.get("dag_run")
        if dag_run is not None:
            return f"{dag_run.dag_id}:{dag_run.run_id}"
    except Exception:
        pass
    return str(uuid.uuid4())


def raw_postgres_env(config: PostgresConfig) -> dict[str, str]:
    return {
        "RAW_PGHOST": config.host,
        "RAW_PGPORT": str(config.port),
        "RAW_PGUSER": config.user,
        "RAW_PGPASSWORD": config.password,
        "RAW_PGDATABASE": config.database,
    }


def matching_postgres_env(config: PostgresConfig) -> dict[str, str]:
    return {
        "DB_HOST": config.host,
        "DB_PORT": str(config.port),
        "DB_USER": config.user,
        "DB_PASSWORD": config.password,
        "DB_NAME": config.database,
        "PGHOST": config.host,
        "PGPORT": str(config.port),
        "PGUSER": config.user,
        "PGPASSWORD": config.password,
        "PGDATABASE": config.database,
        "CLEAN_SCHEMA": config_value("CLEAN_SCHEMA", "cleanned"),
        "MATCH_SCHEMA": config_value("MATCH_SCHEMA", "matching"),
    }


def parse_fdrive() -> None:
    load_id = current_load_id()
    postgres_config = postgres_config_for_new_database()
    raw_env = raw_postgres_env(postgres_config)
    print(
        "FDrive raw DB: "
        f"{postgres_config.user}@{postgres_config.host}:{postgres_config.port}/{postgres_config.database}",
        flush=True,
    )
    run_cmd(
        [
            sys.executable,
            str(PARSERS_DIR / "fdrive.py"),
            "https://fdrive.kz/tyres/almaty",
            "--out",
            str(DATA_DIR / "fdrive_tyres_almaty_full.csv"),
            "--dedupe",
            "--max-products",
            "0",
            "--stream-raw-db",
            "--raw-schema",
            config_value("RAW_SCHEMA", "raw"),
            "--load-id",
            load_id,
            "--raw-table",
            "fdrive_tires",
            "--create-database",
            "--maintenance-database",
            config_value("MARKETPLACE_MAINTENANCE_DATABASE", "postgres"),
            "--no-csv",
        ],
        extra_env=raw_env,
    )
    run_cmd(
        [
            sys.executable,
            str(PARSERS_DIR / "fdrive.py"),
            "https://fdrive.kz/almaty/c/masla-i-zhidkosti/f",
            "--out",
            str(DATA_DIR / "fdrive_masla_i_zhidkosti_full.csv"),
            "--dedupe",
            "--max-products",
            "0",
            "--stream-raw-db",
            "--raw-schema",
            config_value("RAW_SCHEMA", "raw"),
            "--load-id",
            load_id,
            "--raw-table",
            "fdrive_oils",
            "--create-database",
            "--maintenance-database",
            config_value("MARKETPLACE_MAINTENANCE_DATABASE", "postgres"),
            "--no-csv",
        ],
        extra_env=raw_env,
    )
    run_cmd(
        [
            sys.executable,
            str(PARSERS_DIR / "fdrive.py"),
            "https://fdrive.kz/almaty/c/akkumulyatory/f",
            "--out",
            str(DATA_DIR / "fdrive_akkumulyatory_full.csv"),
            "--dedupe",
            "--max-products",
            "0",
            "--group",
            "batteries",
            "--stream-raw-db",
            "--raw-schema",
            config_value("RAW_SCHEMA", "raw"),
            "--load-id",
            load_id,
            "--raw-table",
            "fdrive_batteries",
            "--create-database",
            "--maintenance-database",
            config_value("MARKETPLACE_MAINTENANCE_DATABASE", "postgres"),
            "--no-csv",
        ],
        extra_env=raw_env,
    )


def parse_carcity() -> None:
    load_id = current_load_id()
    postgres_config = postgres_config_for_new_database()
    args = [
        sys.executable,
        str(PARSERS_DIR / "carcity.py"),
        "--categories",
        "all",
        "--workers",
        config_value("CARCITY_WORKERS", config_value("PARSER_WORKERS", "6")),
        "--output-dir",
        str(DATA_DIR / "carcity"),
        "--stream-raw-db",
        "--raw-schema",
        config_value("RAW_SCHEMA", "raw"),
        "--load-id",
        load_id,
        "--create-database",
        "--maintenance-database",
        config_value("MARKETPLACE_MAINTENANCE_DATABASE", "postgres"),
    ]
    if env_flag("CARCITY_NO_ROBOTS", True):
        args.append("--no-robots")
    run_cmd(args, extra_env=raw_postgres_env(postgres_config))


def parse_satu() -> None:
    load_id = current_load_id()
    postgres_config = postgres_config_for_new_database()
    runs_dir = DATA_DIR / "_runs" / "satu"
    runs_dir.mkdir(parents=True, exist_ok=True)
    args = [
        sys.executable,
        str(PARSERS_DIR / "satu_parser.py"),
        "--max-products",
        "0",
        "--max-products-per-category",
        "0",
        "--max-pages",
        config_value("SATU_MAX_PAGES", "1000"),
        "--workers",
        config_value("SATU_WORKERS", config_value("PARSER_WORKERS", "6")),
        "--output-dir",
        str(runs_dir),
        "--stream-raw-db",
        "--raw-schema",
        config_value("RAW_SCHEMA", "raw"),
        "--load-id",
        load_id,
        "--create-database",
        "--maintenance-database",
        config_value("MARKETPLACE_MAINTENANCE_DATABASE", "postgres"),
    ]
    if env_flag("SATU_SKIP_DETAILS"):
        args.append("--skip-details")
    run_cmd(args, extra_env=raw_postgres_env(postgres_config))


def parse_forte_market() -> None:
    load_id = current_load_id()
    postgres_config = postgres_config_for_new_database()
    runs_dir = DATA_DIR / "_runs" / "forte_market"
    runs_dir.mkdir(parents=True, exist_ok=True)
    args = [
        sys.executable,
        str(PARSERS_DIR / "forte_market_parser.py"),
        "--max-products",
        "0",
        "--max-products-per-category",
        "0",
        "--workers",
        config_value("FORTE_WORKERS", config_value("PARSER_WORKERS", "6")),
        "--output-dir",
        str(runs_dir),
        "--stream-raw-db",
        "--raw-schema",
        config_value("RAW_SCHEMA", "raw"),
        "--load-id",
        load_id,
        "--create-database",
        "--maintenance-database",
        config_value("MARKETPLACE_MAINTENANCE_DATABASE", "postgres"),
    ]
    if env_flag("FORTE_SKIP_DETAILS"):
        args.append("--skip-details")
    run_cmd(args, extra_env=raw_postgres_env(postgres_config))


def postgres_config_for_new_database() -> PostgresConfig:
    # Keep parser subprocesses pointed at the marketplace/raw DB, not the
    # Airflow metadata connection. Airflow Connection fdrive_raw_postgres may
    # still exist with a local-only host like "postgres", which is not
    # resolvable in the server deployment.
    return PostgresConfig(
        host=required_config_value("RAW_PGHOST", "PGHOST"),
        port=int(config_value("RAW_PGPORT", config_value("PGPORT", "5432"))),
        user=required_config_value("RAW_PGUSER", "PGUSER"),
        password=required_config_value("RAW_PGPASSWORD", "PGPASSWORD"),
        database=required_config_value("MARKETPLACE_PGDATABASE", "RAW_PGDATABASE", "PGDATABASE"),
    )


def clean_raw_to_cleanned() -> None:
    import psycopg2

    from clean_postgres_tables import clean_database

    config = postgres_config_for_new_database()
    raw_schema = config_value("RAW_SCHEMA", "raw")
    with psycopg2.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        dbname=config.database,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                """,
                (raw_schema,),
            )
            existing_raw_tables = {row[0] for row in cur.fetchall()}

    tables_to_clean = sorted(RAW_TABLES & existing_raw_tables)
    missing_tables = sorted(RAW_TABLES - existing_raw_tables)
    if missing_tables:
        print(f"Skipping missing raw tables: {', '.join(missing_tables)}", flush=True)

    clean_database(
        raw_schema,
        config_value("CLEAN_SCHEMA", "cleanned"),
        tables=tables_to_clean,
        config=config,
        load_id=current_load_id(),
    )


def validate_cleaned_quality() -> None:
    import psycopg2

    config = postgres_config_for_new_database()
    clean_schema = config_value("CLEAN_SCHEMA", "cleanned")
    load_id = current_load_id()
    min_name_pct = float(config_value("QUALITY_MIN_NORMALIZED_NAME_PCT", "0.95"))
    min_source_id_pct = float(config_value("QUALITY_MIN_SOURCE_ID_PCT", "0.99"))
    failures = []
    total_rows = 0

    with psycopg2.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        dbname=config.database,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """,
                (clean_schema,),
            )
            tables = [row[0] for row in cur.fetchall()]

            for table in tables:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    """,
                    (clean_schema, table),
                )
                columns = {row[0] for row in cur.fetchall()}
                if "load_id" not in columns:
                    continue

                cur.execute(
                    f"SELECT COUNT(*) FROM {q_ident(clean_schema)}.{q_ident(table)} WHERE load_id = %s",
                    (load_id,),
                )
                rows = cur.fetchone()[0]
                total_rows += rows
                if rows == 0:
                    print(f"[quality][{table}] no rows for current load_id", flush=True)
                    continue

                print(f"[quality][{table}] rows={rows}", flush=True)
                checks = {
                    "normalized_name": min_name_pct,
                    "source_product_id": min_source_id_pct,
                }
                for column, threshold in checks.items():
                    if column not in columns:
                        failures.append(f"{table}.{column} is missing")
                        continue
                    cur.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM {q_ident(clean_schema)}.{q_ident(table)}
                        WHERE load_id = %s
                          AND NULLIF(TRIM({q_ident(column)}::text), '') IS NOT NULL
                        """,
                        (load_id,),
                    )
                    filled = cur.fetchone()[0]
                    coverage = filled / rows if rows else 0
                    print(f"[quality][{table}] {column} coverage={coverage:.1%}", flush=True)
                    if coverage < threshold:
                        failures.append(f"{table}.{column} coverage {coverage:.1%} < {threshold:.1%}")

                for column in ("brand", "price", "image_url"):
                    if column not in columns:
                        continue
                    cur.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM {q_ident(clean_schema)}.{q_ident(table)}
                        WHERE load_id = %s
                          AND NULLIF(TRIM({q_ident(column)}::text), '') IS NOT NULL
                        """,
                        (load_id,),
                    )
                    filled = cur.fetchone()[0]
                    print(f"[quality][{table}] {column} coverage={filled / rows:.1%}", flush=True)

    if total_rows == 0:
        failures.append(f"No cleaned rows for current load_id={load_id}")
    if failures:
        raise RuntimeError("Cleaned quality gate failed: " + "; ".join(failures))


def ensure_matching_schema() -> None:
    import psycopg2

    config = postgres_config_for_new_database()
    schema = config_value("MATCH_SCHEMA", "matching")
    with psycopg2.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        dbname=config.database,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {q_ident(schema)}")


def category_tree_exists() -> bool:
    import psycopg2

    config = postgres_config_for_new_database()
    schema = config_value("MATCH_SCHEMA", "matching")
    with psycopg2.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        dbname=config.database,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = %s
                      AND table_name = 'categories'
                )
                """,
                (schema,),
            )
            if not cur.fetchone()[0]:
                return False

            cur.execute(f"SELECT COUNT(*) FROM {q_ident(schema)}.{q_ident('categories')}")
            return cur.fetchone()[0] > 0


def branch_on_category_tree() -> str:
    if category_tree_exists():
        return "categories_already_exist"
    return "ensure_categories"


def run_ensure_categories() -> None:
    run_cmd(
        [sys.executable, str(MATCHING_DIR / "ensure_categories.py")],
        extra_env=matching_postgres_env(postgres_config_for_new_database()),
    )


def run_matching_pipeline() -> None:
    run_cmd(
        [sys.executable, str(MATCHING_DIR / "matching_pipeline.py")],
        extra_env=matching_postgres_env(postgres_config_for_new_database()),
    )


def run_build_matching_attributes() -> None:
    run_cmd(
        [
            sys.executable,
            str(SCRIPTS_DIR / "build_matching_attributes.py"),
            "--clean-schema",
            config_value("CLEAN_SCHEMA", "cleanned"),
            "--match-schema",
            config_value("MATCH_SCHEMA", "matching"),
        ],
        extra_env=matching_postgres_env(postgres_config_for_new_database()),
    )


def run_build_sku_price_history() -> None:
    run_cmd(
        [
            sys.executable,
            str(SCRIPTS_DIR / "build_sku_price_history.py"),
            "--clean-schema",
            config_value("CLEAN_SCHEMA", "cleanned"),
            "--match-schema",
            config_value("MATCH_SCHEMA", "matching"),
        ],
        extra_env=matching_postgres_env(postgres_config_for_new_database()),
    )


def validate_matching_quality() -> None:
    import psycopg2

    config = postgres_config_for_new_database()
    schema = config_value("MATCH_SCHEMA", "matching")
    min_multi_source_pct = float(config_value("QUALITY_MIN_MULTI_SOURCE_PCT", "0.005"))
    failures = []
    required_tables = (
        "categories",
        "skus",
        "sku_source_mapping",
        "match_explanations",
        "attributes",
        "attribute_groups",
        "attributes_attribute_groups",
        "category_attributes",
        "sku_attribute_values",
        "sku_price_history",
    )

    with psycopg2.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        dbname=config.database,
    ) as conn:
        with conn.cursor() as cur:
            for table in required_tables:
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
                if not cur.fetchone()[0]:
                    failures.append(f"{schema}.{table} is missing")
                    continue
                cur.execute(f"SELECT COUNT(*) FROM {q_ident(schema)}.{q_ident(table)}")
                count = cur.fetchone()[0]
                print(f"[quality][{schema}.{table}] rows={count}", flush=True)
                if table in {
                    "categories",
                    "skus",
                    "sku_source_mapping",
                    "attributes",
                    "attribute_groups",
                    "category_attributes",
                    "sku_attribute_values",
                    "sku_price_history",
                } and count == 0:
                    failures.append(f"{schema}.{table} is empty")

            cur.execute(
                f"""
                SELECT
                    COUNT(*) AS sku_count,
                    COUNT(*) FILTER (
                        WHERE jsonb_typeof(source_id) = 'array'
                          AND jsonb_array_length(source_id) > 1
                    ) AS multi_source_count
                FROM {q_ident(schema)}.skus
                """
            )
            sku_count, multi_source_count = cur.fetchone()
            multi_source_pct = multi_source_count / sku_count if sku_count else 0
            print(
                f"[quality][matching] multi_source={multi_source_count}/{sku_count} ({multi_source_pct:.2%})",
                flush=True,
            )
            if sku_count and multi_source_pct < min_multi_source_pct:
                failures.append(
                    f"multi-source SKU coverage {multi_source_pct:.2%} < {min_multi_source_pct:.2%}"
                )

    if failures:
        raise RuntimeError("Matching quality gate failed: " + "; ".join(failures))


default_args = {
    "owner": "fdrive",
    "retries": 2,
    "retry_delay": timedelta(minutes=15),
}


with DAG(
    dag_id="marketplace_parsers_to_postgres",
    description="Parse FDrive, Carcity, Forte and Satu into a dedicated PostgreSQL database.",
    start_date=datetime(2026, 6, 1),
    schedule_interval=timedelta(days=3),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["fdrive", "carcity", "forte", "satu", "postgres"],
) as dag:
    start = EmptyOperator(task_id="start")

    parse_fdrive_task = PythonOperator(
        task_id="parse_fdrive",
        python_callable=parse_fdrive,
        execution_timeout=timedelta(hours=12),
    )
    parse_carcity_task = PythonOperator(
        task_id="parse_carcity",
        python_callable=parse_carcity,
        execution_timeout=timedelta(hours=24),
    )
    parse_forte_task = PythonOperator(
        task_id="parse_forte",
        python_callable=parse_forte_market,
        execution_timeout=timedelta(hours=24),
    )
    parse_satu_task = PythonOperator(
        task_id="parse_satu",
        python_callable=parse_satu,
        execution_timeout=timedelta(hours=24),
    )

    clean_to_cleanned = PythonOperator(
        task_id="clean_to_cleanned",
        python_callable=clean_raw_to_cleanned,
        execution_timeout=timedelta(hours=4),
    )
    validate_cleaned = PythonOperator(
        task_id="validate_cleaned_quality",
        python_callable=validate_cleaned_quality,
        execution_timeout=timedelta(minutes=20),
    )
    create_matching_schema = PythonOperator(
        task_id="create_matching_schema",
        python_callable=ensure_matching_schema,
        execution_timeout=timedelta(minutes=10),
    )
    choose_matching_path = BranchPythonOperator(
        task_id="branch_on_category_tree",
        python_callable=branch_on_category_tree,
        execution_timeout=timedelta(minutes=10),
    )
    categories_already_exist = EmptyOperator(task_id="categories_already_exist")
    ensure_categories_task = PythonOperator(
        task_id="ensure_categories",
        python_callable=run_ensure_categories,
        execution_timeout=timedelta(minutes=30),
    )
    run_matching = PythonOperator(
        task_id="run_matching",
        python_callable=run_matching_pipeline,
        execution_timeout=timedelta(hours=6),
        trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
    )
    build_matching_attributes = PythonOperator(
        task_id="build_matching_attributes",
        python_callable=run_build_matching_attributes,
        execution_timeout=timedelta(hours=2),
    )
    build_sku_price_history = PythonOperator(
        task_id="build_sku_price_history",
        python_callable=run_build_sku_price_history,
        execution_timeout=timedelta(hours=1),
    )
    validate_matching = PythonOperator(
        task_id="validate_matching_quality",
        python_callable=validate_matching_quality,
        execution_timeout=timedelta(minutes=20),
    )

    end = EmptyOperator(task_id="end")

    start >> [
        parse_fdrive_task,
        parse_carcity_task,
        parse_forte_task,
        parse_satu_task,
    ] >> clean_to_cleanned >> validate_cleaned >> create_matching_schema >> choose_matching_path

    choose_matching_path >> categories_already_exist >> run_matching
    choose_matching_path >> ensure_categories_task >> run_matching
    run_matching >> build_matching_attributes >> build_sku_price_history >> validate_matching >> end
