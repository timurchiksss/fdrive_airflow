from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
import json
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.exceptions import AirflowNotFoundException
from airflow.hooks.base import BaseHook
from airflow.models import Variable
from airflow.operators.python import PythonOperator


PROJECT_ROOT = Path(os.environ.get("FDRIVE_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
DATA_DIR = PROJECT_ROOT / "data"
PARSERS_DIR = PROJECT_ROOT / "parsers"
NURADIL_DIR = PARSERS_DIR / "code for parser"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# Quick row limits for testing. Env vars and Airflow Variables with the same
# names still override these values, so server config can stay outside code.
ROW_LIMITS = {
    "PARSER_MAX_ROWS": 15000,
    "NORMALIZED_MAX_ROWS": 150,
    "F7_MAX_PRODUCTS": 150,
    "SHINLINE_MAX_PRODUCTS": 150,
    "FDRIVE_TYRES_MAX_PRODUCTS": 150,
    "FDRIVE_OILS_MAX_PRODUCTS": 150,
    "ALMATYRES_MAX_PRODUCTS": 150,
    "CARCITY_MAX_PRODUCTS": 150,
    "PITSTOP_MAX_PRODUCTS": 150,
    "SATU_MAX_PRODUCTS": 150,
    "FORTE_MAX_PRODUCTS": 150,
}

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from raw_postgres_loader import PostgresConfig, config_from_env, initialize_database, load_csvs  # noqa: E402
from normalize_catalog_csvs import normalize as normalize_catalog_csvs  # noqa: E402


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


def parser_limit(variable_name: str) -> str:
    specific_value = optional_config_value(variable_name)
    if specific_value is not None:
        return specific_value
    if variable_name in ROW_LIMITS:
        return str(ROW_LIMITS[variable_name])
    return optional_config_value("PARSER_MAX_ROWS") or str(ROW_LIMITS["PARSER_MAX_ROWS"])


def normalize_source(source: str) -> None:
    normalize_catalog_csvs(
        DATA_DIR,
        max_rows=int(parser_limit("NORMALIZED_MAX_ROWS")),
        sources={source},
    )


def env_flag(name: str, default: bool = False) -> bool:
    value = config_value(name, "true" if default else "false").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def run_cmd(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    command_env["PYTHONPATH"] = os.pathsep.join(
        str(path)
        for path in [
            PROJECT_ROOT,
            PARSERS_DIR,
            NURADIL_DIR,
            command_env.get("PYTHONPATH", ""),
        ]
        if str(path)
    )
    if env:
        command_env.update(env)
    print(f"Running command: {' '.join(args)}", flush=True)
    result = subprocess.run(
        args,
        cwd=str(cwd or PROJECT_ROOT),
        env=command_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.stdout:
        print(result.stdout, flush=True)
    if result.returncode and not allow_failure:
        raise subprocess.CalledProcessError(result.returncode, args, output=result.stdout)
    return result


def run_dirs(base_dir: Path) -> set[Path]:
    return {path for path in base_dir.iterdir() if path.is_dir()}


def latest_run_file(base_dir: Path, file_name: str, directories: set[Path] | None = None) -> Path:
    search_dirs = directories if directories is not None else run_dirs(base_dir)
    candidates = sorted(
        (path / file_name for path in search_dirs),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No {file_name} found under {base_dir}")


def latest_run_summary(base_dir: Path, directories: set[Path] | None = None) -> dict:
    try:
        summary_path = latest_run_file(base_dir, "run_summary.json", directories=directories)
    except FileNotFoundError:
        return {}
    return json.loads(summary_path.read_text(encoding="utf-8"))


def copy_latest_parser_csv(
    runs_dir: Path,
    csv_name: str,
    target_path: Path,
    result: subprocess.CompletedProcess[str],
    directories: set[Path] | None = None,
) -> None:
    try:
        csv_path = latest_run_file(runs_dir, csv_name, directories=directories)
    except FileNotFoundError:
        if result.returncode:
            raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout)
        raise

    summary = latest_run_summary(runs_dir, directories=directories)
    flat_products = int(summary.get("flat_products") or 0)
    raw_products = int(summary.get("raw_products") or 0)
    if result.returncode:
        if flat_products == 0 and raw_products == 0:
            raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout)
        print(
            f"Parser exited with {result.returncode}, but {csv_path} exists. "
            f"Using partial output. Summary: {summary}",
            flush=True,
        )
    shutil.copy2(csv_path, target_path)


def parse_f7() -> None:
    run_cmd(
        [
            sys.executable,
            str(PARSERS_DIR / "f7.py"),
            "--output-dir",
            str(DATA_DIR / "f7"),
            "--max-products",
            parser_limit("F7_MAX_PRODUCTS"),
        ]
    )
    normalize_source("f7")


def parse_shinline() -> None:
    run_cmd(
        [
            sys.executable,
            str(PARSERS_DIR / "shinline.py"),
            "--output-dir",
            str(DATA_DIR / "shinline"),
            "--max-products",
            parser_limit("SHINLINE_MAX_PRODUCTS"),
        ]
    )
    normalize_source("shinline")


def parse_fdrive() -> None:
    run_cmd(
        [
            sys.executable,
            str(PARSERS_DIR / "fdrive.py"),
            "https://fdrive.kz/tyres/almaty",
            "--out",
            str(DATA_DIR / "fdrive_tyres_almaty_full.csv"),
            "--jsonl",
            str(DATA_DIR / "fdrive_tyres_almaty_full.jsonl"),
            "--dedupe",
            "--max-products",
            parser_limit("FDRIVE_TYRES_MAX_PRODUCTS"),
        ]
    )
    run_cmd(
        [
            sys.executable,
            str(PARSERS_DIR / "fdrive.py"),
            "https://fdrive.kz/almaty/c/masla-i-zhidkosti/f",
            "--out",
            str(DATA_DIR / "fdrive_masla_i_zhidkosti_full.csv"),
            "--jsonl",
            str(DATA_DIR / "fdrive_masla_i_zhidkosti_full.jsonl"),
            "--dedupe",
            "--max-products",
            parser_limit("FDRIVE_OILS_MAX_PRODUCTS"),
        ]
    )
    normalize_source("fdrive")


def parse_almatyres() -> None:
    run_cmd(
        [
            sys.executable,
            str(PARSERS_DIR / "almatyres.py"),
            "--out-products",
            str(DATA_DIR / "almatyres_products.csv"),
            "--out-products-jsonl",
            str(DATA_DIR / "almatyres_products.jsonl"),
            "--out-categories",
            str(DATA_DIR / "almatyres_categories.csv"),
            "--max-products",
            parser_limit("ALMATYRES_MAX_PRODUCTS"),
        ]
    )
    normalize_source("almatyres")


def parse_nuradil_sources() -> None:
    run_cmd(
        [
            sys.executable,
            "run.py",
            "--site",
            "carcity",
            "--categories",
            "all",
            "--workers",
            config_value("PARSER_WORKERS", "6"),
            "--per-group",
            parser_limit("CARCITY_MAX_PRODUCTS"),
        ],
        cwd=NURADIL_DIR,
    )
    run_cmd([sys.executable, "split_by_category.py", str(DATA_DIR / "carcity" / "carcity_products.csv")], cwd=NURADIL_DIR)
    run_cmd([sys.executable, "profile.py", "--site", "carcity"], cwd=NURADIL_DIR)

    run_cmd(
        [
            sys.executable,
            "run.py",
            "--site",
            "pitstopshop",
            "--roots",
            config_value("PITSTOP_ROOTS", "tyre,gruz,sh,moto,atv"),
            "--workers",
            config_value("PARSER_WORKERS", "6"),
            "--limit",
            parser_limit("PITSTOP_MAX_PRODUCTS"),
        ],
        cwd=NURADIL_DIR,
    )
    run_cmd([sys.executable, "profile.py", "--site", "pitstopshop"], cwd=NURADIL_DIR)
    run_cmd(
        [sys.executable, "split_by_category.py", str(DATA_DIR / "pitstopshop" / "pitstopshop_products.csv")],
        cwd=NURADIL_DIR,
    )
    normalize_source("carcity")
    normalize_source("pitstopshop")


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
        parser_limit("SATU_MAX_PRODUCTS"),
        "--max-pages",
        config_value("SATU_MAX_PAGES", "1000"),
        "--output-dir",
        str(runs_dir),
        "--direct-http",
    ]
    if env_flag("SATU_SKIP_DETAILS"):
        args.append("--skip-details")
    result = run_cmd(args, allow_failure=True)
    new_dirs = run_dirs(runs_dir) - before_dirs
    copy_latest_parser_csv(
        runs_dir,
        "satu_products.csv",
        DATA_DIR / "satu_products.csv",
        result,
        directories=new_dirs or None,
    )
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
        parser_limit("FORTE_MAX_PRODUCTS"),
        "--output-dir",
        str(runs_dir),
    ]
    if env_flag("FORTE_SKIP_DETAILS"):
        args.append("--skip-details")
    result = run_cmd(args, allow_failure=True)
    new_dirs = run_dirs(runs_dir) - before_dirs
    copy_latest_parser_csv(
        runs_dir,
        "forte_products.csv",
        DATA_DIR / "forte_productsname_normalization.csv",
        result,
        directories=new_dirs or None,
    )
    normalize_source("forte_market")


def postgres_config_from_connection() -> PostgresConfig:
    try:
        conn = BaseHook.get_connection(Variable.get("RAW_POSTGRES_CONN_ID", default_var="fdrive_raw_postgres"))
    except AirflowNotFoundException:
        return config_from_env()

    return PostgresConfig(
        host=conn.host or "postgres",
        port=conn.port or 5432,
        user=conn.login or "airflow",
        password=conn.password or os.environ.get("RAW_PGPASSWORD") or os.environ.get("PGPASSWORD", "airflow"),
        database=conn.schema or "airflow",
    )


def load_to_postgres() -> str:
    load_id = str(uuid.uuid4())
    schema = config_value("RAW_SCHEMA", "raw")
    return load_csvs(
        DATA_DIR,
        schema,
        postgres_config_from_connection(),
        load_id=load_id,
        strict=True,
    )


def clean_to_postgres() -> None:
    from clean_postgres_tables import clean_database

    clean_database(
        config_value("RAW_SCHEMA", "raw"),
        config_value("CLEAN_SCHEMA", "cleanned"),
    )


def match_categories() -> None:
    run_cmd(
        [
            sys.executable,
            str(SCRIPTS_DIR / "category_matching.py"),
            "--clean-schema",
            config_value("CLEAN_SCHEMA", "cleanned"),
            "--output-schema",
            config_value("MATCH_SCHEMA", "matching"),
            "--output-table",
            config_value("MATCH_TABLE", "category_matches"),
        ]
    )


def init_postgres_schema() -> None:
    initialize_database(
        postgres_config_from_connection(),
        config_value("RAW_SCHEMA", "raw"),
        DATA_DIR,
    )


default_args = {
    "owner": "fdrive",
    "retries": 2,
    "retry_delay": timedelta(minutes=15),
}


with DAG(
    dag_id="marketplace_parsers_to_postgres",
    description="Parse marketplace CSV datasets every 3 days and refresh raw Postgres tables.",
    start_date=datetime(2026, 6, 1),
    schedule_interval=timedelta(days=3),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["parsers", "postgres", "raw"],
) as dag:
    init_postgres_task = PythonOperator(
        task_id="init_postgres_schema",
        python_callable=init_postgres_schema,
        execution_timeout=timedelta(minutes=10),
    )
    parse_f7_task = PythonOperator(
        task_id="parse_f7",
        python_callable=parse_f7,
        execution_timeout=timedelta(hours=8),
    )
    parse_shinline_task = PythonOperator(
        task_id="parse_shinline",
        python_callable=parse_shinline,
        execution_timeout=timedelta(hours=8),
    )
    parse_fdrive_task = PythonOperator(
        task_id="parse_fdrive",
        python_callable=parse_fdrive,
        execution_timeout=timedelta(hours=8),
    )
    parse_almatyres_task = PythonOperator(
        task_id="parse_almatyres",
        python_callable=parse_almatyres,
        execution_timeout=timedelta(hours=12),
    )
    parse_nuradil_task = PythonOperator(
        task_id="parse_carcity_and_pitstopshop",
        python_callable=parse_nuradil_sources,
        execution_timeout=timedelta(hours=16),
    )
    parse_satu_task = PythonOperator(
        task_id="parse_satu",
        python_callable=parse_satu,
        execution_timeout=timedelta(hours=12),
    )
    parse_forte_task = PythonOperator(
        task_id="parse_forte_market",
        python_callable=parse_forte_market,
        execution_timeout=timedelta(hours=12),
    )
    load_task = PythonOperator(
        task_id="load_csvs_to_postgres",
        python_callable=load_to_postgres,
        execution_timeout=timedelta(hours=4),
    )
    clean_task = PythonOperator(
        task_id="clean_raw_to_cleanned",
        python_callable=clean_to_postgres,
        execution_timeout=timedelta(hours=2),
    )
    match_task = PythonOperator(
        task_id="match_categories",
        python_callable=match_categories,
        execution_timeout=timedelta(hours=4),
    )

    init_postgres_task >> [
        parse_f7_task,
        parse_shinline_task,
        parse_fdrive_task,
        parse_almatyres_task,
        parse_nuradil_task,
        parse_satu_task,
        parse_forte_task,
    ] >> load_task >> clean_task >> match_task
