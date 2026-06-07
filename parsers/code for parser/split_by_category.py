#!/usr/bin/env python3
"""Разрезает широкий carcity_products.csv на отдельные файлы по категориям.

В каждый файл — общий «паспорт товара» + только свои атрибуты категории.
Нераспознанные категории не теряются (carcity_uncategorized.csv).

Запуск:  python3 split_by_category.py [путь_к_csv]
По умолчанию: data/carcity_products.csv -> data/carcity_<категория>.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_INPUT = DATA_DIR / "carcity" / "carcity_products.csv"

# Нормализация значений category_group (рус/англ) -> канон.
CATEGORY_ALIASES = {
    "tires": "tires", "tire": "tires", "tyre": "tires", "tyres": "tires",
    "шины": "tires", "шина": "tires",
    "oils": "oils", "oil": "oils", "масла": "oils", "масло": "oils",
    "batteries": "batteries", "battery": "batteries",
    "акб": "batteries", "аккумуляторы": "batteries", "аккумулятор": "batteries",
    "filters": "filters", "filter": "filters", "фильтры": "filters", "фильтр": "filters",
}

# Схему берём из единого источника — models (чтобы не было рассинхрона).
from freedom_parser.common.models import ATTRS_BY_GROUP as ATTR_COLUMNS  # noqa: E402
from freedom_parser.common.models import COMMON_COLUMNS  # noqa: E402


def normalize_category(value: str) -> str | None:
    return CATEGORY_ALIASES.get(str(value).strip().lower())


def main() -> None:
    inp = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    if not inp.exists():
        raise SystemExit(f"Нет входного файла: {inp}")

    # req 1: строки, без подмены пустых на NaN -> сохраняем ведущие нули.
    df = pd.read_csv(inp, dtype=str, keep_default_na=False)
    total = len(df)

    # req 2: нормализованная категория в отдельной служебной колонке.
    df["_cat"] = df["category_group"].map(normalize_category)

    out_dir = inp.parent
    # Префикс берём из имени файла: carcity_products.csv -> carcity_, altraauto_products.csv -> altraauto_.
    prefix = inp.stem.replace("_products", "")
    report: list[tuple[str, int, Path]] = []

    # req 4-5,7: по каждой целевой категории — общие + только свои существующие колонки.
    for cat, attrs in ATTR_COLUMNS.items():
        sub = df[df["_cat"] == cat]
        cols = [c for c in (COMMON_COLUMNS + attrs) if c in df.columns]
        path = out_dir / f"{prefix}_{cat}.csv"
        sub[cols].to_csv(path, index=False, encoding="utf-8-sig")
        report.append((cat, len(sub), path))

    # req 6: нераспознанные категории — со всеми колонками, чтобы ничего не потерять.
    unknown = df[df["_cat"].isna()]
    full_cols = [c for c in df.columns if c != "_cat"]
    unc_path = out_dir / f"{prefix}_uncategorized.csv"
    unknown[full_cols].to_csv(unc_path, index=False, encoding="utf-8-sig")
    report.append(("uncategorized", len(unknown), unc_path))

    # req 8: отчёт + проверка целостности.
    print(f"Вход: {inp}  ({total} строк)\n")
    print(f"{'категория':16s} {'строк':>8s}  файл")
    written = 0
    for cat, n, path in report:
        written += n
        print(f"  {cat:14s} {n:8d}  {path.name}")
    print(f"\n  {'ИТОГО':14s} {written:8d}")
    ok = written == total
    print(f"\nПроверка целостности: {written} == {total}  ->  "
          f"{'✅ ничего не потеряно' if ok else '❌ РАСХОЖДЕНИЕ!'}")


if __name__ == "__main__":
    main()
