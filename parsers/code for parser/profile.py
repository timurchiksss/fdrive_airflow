#!/usr/bin/env python3
"""Data Profiling (шаг 1 pipeline) по собранному CSV одного источника.

Печатает:
  A) объёмы по группам и листовым категориям;
  B) полноту обязательных атрибутов ПО КАЖДОЙ группе (KPI атрибуции ≥80%);
  C) потенциальные дубли внутри источника.
И выгружает строки с пропусками обязательных атрибутов в
`data/<site>_quality_gaps.csv` — это «лог что не распарсилось» для отчёта.

Запуск:  python3 profile.py --site carcity
"""
from __future__ import annotations

import argparse

import pandas as pd

import config

# Обязательные атрибуты по группам (раздел 4 ТЗ). brand — общий.
REQUIRED = {
    "tires": ["brand", "tire_width", "tire_profile", "tire_diameter",
              "season", "load_index", "speed_index", "runflat", "studded"],
    "oils": ["brand", "viscosity", "volume_liters", "oil_type"],
    "batteries": ["brand", "capacity_ah", "voltage_v", "polarity"],
    "filters": ["brand", "filter_type"],
}
KPI_THRESHOLD = 80.0


def _filled(series: pd.Series) -> pd.Series:
    """Маска «значение заполнено» (не пусто и не строковый None)."""
    s = series.fillna("").astype(str).str.strip()
    return (s != "") & (s.str.lower() != "none")


def profile(site: str) -> None:
    out_dir = config.site_dir(site)
    path = out_dir / f"{site}_products.csv"
    if not path.exists():
        raise SystemExit(f"Нет файла {path} — сначала запустите парсер для {site}.")
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    print(f"\n=== PROFILING: {site} ===  всего строк: {len(df)}")

    # A) Объёмы
    print("\n— A. Объёмы по группам —")
    print(df["category_group"].value_counts().to_string())
    print("\n— Топ листовых категорий —")
    print(df["category_leaf"].value_counts().head(12).to_string())

    # B) Полнота обязательных атрибутов по группам (KPI)
    print("\n— B. Полнота обязательных атрибутов по группам (KPI ≥80%) —")
    gap_rows = []
    for group, cols in REQUIRED.items():
        sub = df[df["category_group"] == group]
        if len(sub) == 0:
            continue
        print(f"\n  [{group}]  ({len(sub)} строк)")
        missing_mask = pd.Series(False, index=sub.index)
        for c in cols:
            if c not in sub.columns:
                print(f"    ❌ {c:16s} НЕТ КОЛОНКИ")
                continue
            filled = _filled(sub[c])
            pct = 100.0 * filled.sum() / len(sub)
            flag = "✅" if pct >= KPI_THRESHOLD else "⚠️"
            print(f"    {flag} {c:16s} {pct:5.1f}%")
            missing_mask |= ~filled
        gaps = sub[missing_mask].copy()
        if len(gaps):
            gaps["_missing"] = gaps.apply(
                lambda r: ",".join(c for c in cols if c in sub.columns and not _filled(pd.Series([r[c]])).iloc[0]),
                axis=1,
            )
            gap_rows.append(gaps)

    # C) Дубли внутри источника
    print("\n— C. Потенциальные дубли внутри источника —")
    dups = df[df.duplicated(subset=["name", "brand"], keep=False)]
    print(f"  строк с повторяющимися (name, brand): {len(dups)}")
    if len(dups):
        sample = dups.sort_values(["brand", "name"])[["brand", "name", "source_product_id"]].head(6)
        print(sample.to_string(index=False))

    # Экспорт пропусков
    gaps_path = out_dir / f"{site}_quality_gaps.csv"
    if gap_rows:
        out = pd.concat(gap_rows)[["source", "source_product_id", "category_group",
                                   "name", "brand", "_missing"]]
        out.to_csv(gaps_path, index=False, encoding="utf-8-sig")
        print(f"\n  Пропуски обязательных атрибутов: {len(out)} строк -> {gaps_path}")
    else:
        pd.DataFrame(columns=["source", "source_product_id", "category_group", "name", "brand", "_missing"]).to_csv(
            gaps_path,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"\n  Пропуски обязательных атрибутов: 0 строк -> {gaps_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Профайлинг собранного CSV")
    ap.add_argument("--site", choices=["carcity", "pitstopshop", "altraauto", "expertoil"], required=True)
    args = ap.parse_args()
    profile(args.site)


if __name__ == "__main__":
    main()
