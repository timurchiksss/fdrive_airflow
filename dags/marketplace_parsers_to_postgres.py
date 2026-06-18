from __future__ import annotations

import json
import os
import shutil
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

from normalize_catalog_csvs import normalize as normalize_catalog_csvs  # noqa: E402
from raw_postgres_loader import PostgresConfig, load_csvs, q_ident  # noqa: E402


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
    result = subprocess.run(
        args,
        cwd=str(PROJECT_ROOT),
        env=command_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.stdout:
        print(result.stdout, flush=True)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, args, output=result.stdout)
    return result


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


def normalize_source(source: str) -> None:
    normalize_catalog_csvs(DATA_DIR, max_rows=0, sources={source})


def run_dirs(base_dir: Path) -> set[Path]:
    return {path for path in base_dir.iterdir() if path.is_dir()}


def latest_run_file(base_dir: Path, file_name: str, directories: set[Path]) -> Path:
    for directory in sorted(directories, key=lambda path: path.name, reverse=True):
        candidate = directory / file_name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No {file_name} found under {base_dir}")


def copy_run_outputs(
    runs_dir: Path,
    output_dir: Path,
    prefix: str,
    directories: set[Path],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for group in ["tires", "oils", "filters", "batteries"]:
        source = latest_run_file(runs_dir, f"{prefix}_{group}.csv", directories)
        shutil.copy2(source, output_dir / source.name)

    summary_path = latest_run_file(runs_dir, "run_summary.json", directories)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not summary.get("completed"):
        raise RuntimeError(f"{prefix} parser did not complete: {summary}")


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
        ],
        extra_env=raw_env,
    )
    normalize_source("fdrive")


def parse_carcity() -> None:
    args = [
        sys.executable,
        str(PARSERS_DIR / "carcity.py"),
        "--categories",
        "all",
        "--workers",
        config_value("CARCITY_WORKERS", config_value("PARSER_WORKERS", "6")),
        "--output-dir",
        str(DATA_DIR / "carcity"),
    ]
    if env_flag("CARCITY_NO_ROBOTS", True):
        args.append("--no-robots")
    run_cmd(args)
    normalize_source("carcity")


def parse_satu() -> None:
    runs_dir = DATA_DIR / "_runs" / "satu"
    runs_dir.mkdir(parents=True, exist_ok=True)
    before_dirs = run_dirs(runs_dir)
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
    ]
    if env_flag("SATU_SKIP_DETAILS"):
        args.append("--skip-details")
    run_cmd(args)
    new_dirs = run_dirs(runs_dir) - before_dirs
    if not new_dirs:
        raise RuntimeError("Satu parser did not create a run directory.")
    copy_run_outputs(runs_dir, DATA_DIR / "satu", "satu", new_dirs)
    normalize_source("satu")


def parse_forte_market() -> None:
    runs_dir = DATA_DIR / "_runs" / "forte_market"
    runs_dir.mkdir(parents=True, exist_ok=True)
    before_dirs = run_dirs(runs_dir)
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
    ]
    if env_flag("FORTE_SKIP_DETAILS"):
        args.append("--skip-details")
    run_cmd(args)
    new_dirs = run_dirs(runs_dir) - before_dirs
    if not new_dirs:
        raise RuntimeError("Forte parser did not create a run directory.")
    copy_run_outputs(runs_dir, DATA_DIR / "forte_market", "forte", new_dirs)
    normalize_source("forte_market")


def postgres_config_for_new_database() -> PostgresConfig:
    # Keep parser subprocesses pointed at the marketplace/raw DB, not the
    # Airflow metadata connection. Airflow Connection fdrive_raw_postgres may
    # still exist with a local-only host like "postgres", which is not
    # resolvable in the server deployment.
    return PostgresConfig(
        host=config_value("RAW_PGHOST", config_value("PGHOST", "fdrivedataairflow-fdrive-ucfmoa")),
        port=int(config_value("RAW_PGPORT", config_value("PGPORT", "5432"))),
        user=config_value("RAW_PGUSER", config_value("PGUSER", "postgres")),
        password=config_value("RAW_PGPASSWORD", config_value("PGPASSWORD", "scSD6QCahyMhCsdxyW10")),
        database=config_value(
            "MARKETPLACE_PGDATABASE",
            config_value("RAW_PGDATABASE", config_value("PGDATABASE", "fdrive")),
        ),
    )


def load_raw_to_new_database() -> str:
    return load_csvs(
        DATA_DIR,
        config_value("RAW_SCHEMA", "raw"),
        postgres_config_for_new_database(),
        load_id=current_load_id(),
        strict=True,
        tables=RAW_TABLES,
        create_database=True,
        maintenance_database=config_value("MARKETPLACE_MAINTENANCE_DATABASE", "postgres"),
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
    )


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

    load_raw = PythonOperator(
        task_id="load_raw",
        python_callable=load_raw_to_new_database,
        execution_timeout=timedelta(hours=4),
    )
    clean_to_cleanned = PythonOperator(
        task_id="clean_to_cleanned",
        python_callable=clean_raw_to_cleanned,
        execution_timeout=timedelta(hours=4),
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

    end = EmptyOperator(task_id="end")

    start >> [
        parse_fdrive_task,
        parse_carcity_task,
        parse_forte_task,
        parse_satu_task,
    ] >> load_raw >> clean_to_cleanned >> create_matching_schema >> choose_matching_path

    choose_matching_path >> categories_already_exist >> run_matching
    choose_matching_path >> ensure_categories_task >> run_matching
    run_matching >> end
