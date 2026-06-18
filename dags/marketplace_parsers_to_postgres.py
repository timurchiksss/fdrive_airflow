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
from airflow.operators.python import PythonOperator, get_current_context


PROJECT_ROOT = Path(os.environ.get("FDRIVE_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
DATA_DIR = PROJECT_ROOT / "data"
PARSERS_DIR = PROJECT_ROOT / "parsers"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

RAW_TABLES = {
    "fdrive_tires",
    "fdrive_oils",
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
from raw_postgres_loader import PostgresConfig, load_csvs  # noqa: E402


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
        for path in [PROJECT_ROOT, PARSERS_DIR, command_env.get("PYTHONPATH", "")]
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
    from clean_postgres_tables import clean_database

    clean_database(
        config_value("RAW_SCHEMA", "raw"),
        config_value("CLEAN_SCHEMA", "cleanned"),
        tables=sorted(RAW_TABLES),
        config=postgres_config_for_new_database(),
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

    end = EmptyOperator(task_id="end")

    start >> [
        parse_fdrive_task,
        parse_carcity_task,
        parse_forte_task,
        parse_satu_task,
    ] >> load_raw >> clean_to_cleanned >> end
