#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


csv.field_size_limit(sys.maxsize)

BASE_COLUMNS = [
    "source",
    "source_product_id",
    "source_url",
    "category_group",
    "product_name",
    "brand",
    "price",
    "old_price",
    "currency",
    "availability",
    "city",
    "image_url",
    "parsed_at",
    "article_sku",
    "rating",
    "reviews_count",
    "seller_count",
]

SCHEMAS = {
    "tires": BASE_COLUMNS
    + [
        "tire_width",
        "tire_profile",
        "tire_diameter",
        "season",
        "load_index",
        "speed_index",
        "studded",
        "runflat",
        "model_name",
        "weight",
    ],
    "oils": BASE_COLUMNS
    + [
        "viscosity",
        "volume_liters",
        "oil_type",
        "engine_type",
        "specification",
        "product_line",
        "package_type",
        "acea_class",
        "approvals",
    ],
    "batteries": BASE_COLUMNS
    + [
        "capacity_ah",
        "voltage_v",
        "start_current_a",
        "polarity",
        "battery_type",
        "dimensions",
        "terminal_type",
        "weight",
        "features",
        "length",
        "width",
        "height",
    ],
    "filters": BASE_COLUMNS
    + [
        "filter_type",
        "compatible_brand",
        "compatible_model",
        "oem_number",
        "additional_information",
    ],
    "wheels": BASE_COLUMNS
    + [
        "wheel_width",
        "wheel_diameter",
        "bolt_pattern",
        "et",
        "model_name",
    ],
}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def first(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if "|" in text:
        return text.split("|", 1)[0].strip()
    if "," in text and text.startswith(("http://", "https://")):
        return text.split(",", 1)[0].strip()
    return text


def pick(row: dict[str, str], names: list[str]) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def tire_size_from_text(text: str) -> tuple[str, str, str]:
    match = re.search(r"(?P<width>\d{3})\s*/\s*(?P<profile>\d{2,3})\s*(?:R|ZR|/R)?\s*(?P<diameter>\d{2})", text, re.I)
    if match:
        return match.group("width"), match.group("profile"), match.group("diameter")
    match = re.search(r"(?P<width>\d{2,3}(?:\.\d+)?)\s*[xх]\s*(?P<diameter>\d{2,3}(?:\.\d+)?)", text, re.I)
    if match:
        return match.group("width"), "", match.group("diameter")
    return "", "", ""


def infer_group(row: dict[str, str]) -> str:
    text = " ".join(
        pick(row, [name])
        for name in ["category_group", "category", "category_l1", "category_leaf", "product_name", "name", "title"]
    ).lower()
    if any(word in text for word in ["шина", "шин", "tyre", "tire"]):
        return "tires"
    if any(word in text for word in ["масло", "масл", "oil"]):
        return "oils"
    if any(word in text for word in ["аккум", "battery", "батар"]):
        return "batteries"
    if any(word in text for word in ["фильтр", "filter"]):
        return "filters"
    if any(word in text for word in ["диск", "wheel", "wheels"]):
        return "wheels"
    if pick(row, ["width", "profile", "diameter", "tire_width", "tire_profile", "tire_diameter"]):
        return "tires"
    if pick(row, ["viscosity", "volume_liters", "oil_type"]):
        return "oils"
    if pick(row, ["capacity_ah", "voltage_v", "start_current_a"]):
        return "batteries"
    if pick(row, ["filter_type", "oem_number"]):
        return "filters"
    return ""


def base_row(row: dict[str, str], source: str, group: str) -> dict[str, str]:
    return {
        "source": pick(row, ["source"]) or source,
        "source_product_id": pick(row, ["source_product_id", "product_id", "id", "sku_id", "sku", "code"]),
        "source_url": pick(row, ["source_url", "url"]),
        "category_group": group,
        "product_name": pick(row, ["product_name", "name", "title", "full_title", "normalized_name"]),
        "brand": pick(row, ["brand", "Производитель", "Марка", "brand_name", "brand_code"]),
        "price": pick(row, ["price"]),
        "old_price": pick(row, ["old_price", "price_old", "price_without_discount"]),
        "currency": pick(row, ["currency"]) or "KZT",
        "availability": pick(row, ["availability", "quantity_available_text", "quantity_in_stock", "stocks"]),
        "city": pick(row, ["city"]) or "almaty",
        "image_url": first(pick(row, ["image_url", "image", "images", "image_urls"])),
        "parsed_at": pick(row, ["parsed_at", "updated_at", "created_at"]),
        "article_sku": pick(row, ["article_sku", "sku", "code"]),
        "rating": pick(row, ["rating"]),
        "reviews_count": pick(row, ["reviews_count", "review_count"]),
        "seller_count": pick(row, ["seller_count"]),
    }


def canonical_tire(row: dict[str, str], source: str) -> dict[str, str]:
    out = base_row(row, source, "tires")
    size_width, size_profile, size_diameter = tire_size_from_text(out["product_name"])
    out.update(
        {
            "tire_width": pick(row, ["tire_width", "width", "Ширина", "Ширина шины", "Ширина профиля", "Ширина профиля шины"]) or size_width,
            "tire_profile": pick(row, ["tire_profile", "profile", "height", "Высота", "Высота профиля", "Высота профиля шины"]) or size_profile,
            "tire_diameter": pick(
                row,
                [
                    "tire_diameter",
                    "diameter",
                    "Диаметр диска",
                    "Диаметр шины",
                    "Посадочный диаметр",
                    "Посадочный диаметр шины",
                    "Диаметр колеса/диска",
                ],
            )
            or size_diameter,
            "season": pick(row, ["season", "Сезонность", "Сезонность шин"]),
            "load_index": pick(row, ["load_index", "weight_single_index", "Индекс нагрузки", "Индекс нагрузки шины"]),
            "speed_index": pick(row, ["speed_index", "velocity_index", "Индекс скорости"]),
            "studded": pick(row, ["studded", "tyre_stud_type_name", "Шипы"]),
            "runflat": pick(row, ["runflat", "Безопасная шина"]),
            "model_name": pick(row, ["model_name", "Модель", "Модель шины"]),
            "weight": pick(row, ["weight", "Вес"]),
        }
    )
    return out


def canonical_oil(row: dict[str, str], source: str) -> dict[str, str]:
    out = base_row(row, source, "oils")
    out.update(
        {
            "viscosity": pick(row, ["viscosity", "Класс вязкости SAE", "Вязкость по SAE"]),
            "volume_liters": pick(row, ["volume_liters", "Объем упаковки, л"]),
            "oil_type": pick(row, ["oil_type", "Вид масла", "Тип"]),
            "engine_type": pick(row, ["engine_type", "Область применения"]),
            "specification": pick(row, ["specification", "Класс API", "Стандарт API", "Стандарт DOT"]),
            "product_line": pick(row, ["product_line", "Специализация"]),
            "package_type": pick(row, ["package_type"]),
            "acea_class": pick(row, ["acea_class", "Класс ACEA"]),
            "approvals": pick(row, ["approvals", "Допуски", "Допуск"]),
        }
    )
    return out


def canonical_battery(row: dict[str, str], source: str) -> dict[str, str]:
    out = base_row(row, source, "batteries")
    out.update(
        {
            "capacity_ah": pick(row, ["capacity_ah"]),
            "voltage_v": pick(row, ["voltage_v"]),
            "start_current_a": pick(row, ["start_current_a"]),
            "polarity": pick(row, ["polarity"]),
            "battery_type": pick(row, ["battery_type"]),
            "dimensions": pick(row, ["dimensions"]),
            "terminal_type": pick(row, ["terminal_type"]),
            "weight": pick(row, ["weight", "Вес"]),
            "features": pick(row, ["features", "Особенности"]),
            "length": pick(row, ["length", "Длина"]),
            "width": pick(row, ["width", "Ширина"]),
            "height": pick(row, ["height", "Высота"]),
        }
    )
    return out


def canonical_filter(row: dict[str, str], source: str) -> dict[str, str]:
    out = base_row(row, source, "filters")
    out.update(
        {
            "filter_type": pick(row, ["filter_type"]),
            "compatible_brand": pick(row, ["compatible_brand"]),
            "compatible_model": pick(row, ["compatible_model"]),
            "oem_number": pick(row, ["oem_number", "oem_numbers"]),
            "additional_information": pick(
                row,
                ["additional_information", "Дополнительная информация"],
            ),
        }
    )
    return out


def canonical_wheel(row: dict[str, str], source: str) -> dict[str, str]:
    out = base_row(row, source, "wheels")
    out.update(
        {
            "wheel_width": pick(row, ["wheel_width", "Ширина диска"]),
            "wheel_diameter": pick(row, ["wheel_diameter", "Посадочный диаметр диска", "Диаметр диска"]),
            "bolt_pattern": pick(row, ["bolt_pattern", "PCD", "Разболтовка"]),
            "et": pick(row, ["et", "Вылет (ET)", "Вылет"]),
            "model_name": pick(row, ["model_name", "Модель", "Модель диска"]),
        }
    )
    return out


CANONICALIZERS = {
    "tires": canonical_tire,
    "oils": canonical_oil,
    "batteries": canonical_battery,
    "filters": canonical_filter,
    "wheels": canonical_wheel,
}

PER_CATEGORY_LIMITED_OUTPUTS = {
    ("f7_all", "tires"),
    ("forte_market", "batteries"),
    ("forte_market", "filters"),
    ("forte_market", "oils"),
    ("forte_market", "tires"),
    ("satu", "batteries"),
    ("satu", "filters"),
    ("satu", "oils"),
    ("satu", "tires"),
    ("shinline", "tires"),
}


def add_category_file(
    outputs: dict[tuple[str, str], list[dict[str, str]]],
    path: Path,
    source: str,
    group: str,
    output_source: str | None = None,
) -> None:
    canonicalizer = CANONICALIZERS[group]
    for row in read_rows(path):
        outputs[(output_source or source, group)].append(canonicalizer(row, source))


def add_limited_category_file(
    outputs: dict[tuple[str, str], list[dict[str, str]]],
    path: Path,
    source: str,
    group: str,
    output_source: str,
    max_rows: int,
) -> None:
    canonicalizer = CANONICALIZERS[group]
    rows = read_rows(path)
    if max_rows > 0:
        rows = rows[:max_rows]
    for row in rows:
        outputs[(output_source, group)].append(canonicalizer(row, source))


def marketplace_category_key(row: dict[str, str]) -> str:
    return pick(row, ["category_id", "category", "category_l1", "category_leaf"]) or "__uncategorized__"


def add_marketplace_file(
    outputs: dict[tuple[str, str], list[dict[str, str]]],
    path: Path,
    fallback_source: str,
    max_rows_per_category: int = 0,
) -> None:
    category_counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in read_rows(path):
        group = infer_group(row)
        if group not in CANONICALIZERS:
            continue
        category_key = marketplace_category_key(row)
        counter_key = (group, category_key)
        if max_rows_per_category > 0 and category_counts[counter_key] >= max_rows_per_category:
            continue
        category_counts[counter_key] += 1
        source = pick(row, ["source"]) or fallback_source
        outputs[(fallback_source, group)].append(CANONICALIZERS[group](row, source))


def safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return value or "unknown"


def wanted_source(source: str, sources: set[str] | None) -> bool:
    return sources is None or source in sources


def remove_old_outputs(out_dir: Path, sources: set[str] | None) -> None:
    if sources is None:
        for old_file in out_dir.glob("*.csv"):
            old_file.unlink()
        return

    for old_file in out_dir.glob("*.csv"):
        stem = old_file.stem
        if any(stem == source or stem.startswith(f"{source}_") for source in sources):
            old_file.unlink()


def normalize(data_dir: Path, max_rows: int = 15000, sources: set[str] | None = None) -> list[Path]:
    out_dir = data_dir / "normalized"
    out_dir.mkdir(parents=True, exist_ok=True)
    remove_old_outputs(out_dir, sources)

    outputs: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)

    for source in ["carcity", "pitstopshop"]:
        if wanted_source(source, sources):
            for group in ["tires", "oils", "batteries", "filters"]:
                add_category_file(outputs, data_dir / source / f"{source}_{group}.csv", source, group)

    if wanted_source("fdrive", sources):
        add_category_file(outputs, data_dir / "fdrive_tyres_almaty_full.csv", "fdrive", "tires")
        add_category_file(outputs, data_dir / "fdrive_masla_i_zhidkosti_full.csv", "fdrive", "oils")
    if wanted_source("almatyres", sources):
        add_category_file(outputs, data_dir / "almatyres_products.csv", "almatyres", "tires")

    if wanted_source("f7", sources):
        add_category_file(outputs, data_dir / "f7" / "f7_tyres.csv", "f7", "tires")
        add_category_file(outputs, data_dir / "f7" / "f7_trucks.csv", "f7", "tires", output_source="f7_trucks")
        add_category_file(outputs, data_dir / "f7" / "f7_otr.csv", "f7", "tires", output_source="f7_otr")
        for name in ["f7_tyres", "f7_trucks", "f7_otr"]:
            add_limited_category_file(
                outputs,
                data_dir / "f7" / f"{name}.csv",
                "f7",
                "tires",
                "f7_all",
                max_rows,
            )
        add_category_file(outputs, data_dir / "f7" / "f7_wheels.csv", "f7", "wheels")

    if wanted_source("shinline", sources):
        shinline_tire_sources = {
            "legkovye_shiny": "shinline_passenger",
            "gruzovye_shiny": "shinline_truck",
            "legkogruzovye_shiny": "shinline_light_truck",
            "selkhoz_shiny": "shinline_agro",
            "industrial_shiny": "shinline_industrial",
        }
        for name, output_source in shinline_tire_sources.items():
            add_category_file(outputs, data_dir / "shinline" / f"{name}.csv", "shinline", "tires", output_source=output_source)
            add_limited_category_file(
                outputs,
                data_dir / "shinline" / f"{name}.csv",
                "shinline",
                "tires",
                "shinline",
                max_rows,
            )
        add_category_file(outputs, data_dir / "shinline" / "wheels.csv", "shinline", "wheels")

    if wanted_source("satu", sources):
        for group in ["tires", "oils", "batteries", "filters"]:
            add_category_file(
                outputs,
                data_dir / "satu" / f"satu_{group}.csv",
                "satu",
                group,
            )
    if wanted_source("forte_market", sources):
        for group in ["tires", "oils", "batteries", "filters"]:
            add_category_file(
                outputs,
                data_dir / "forte_market" / f"forte_{group}.csv",
                "forte_market",
                group,
            )

    written = []
    for (source, group), rows in sorted(outputs.items()):
        if max_rows > 0 and (source, group) not in PER_CATEGORY_LIMITED_OUTPUTS:
            rows = rows[:max_rows]
        columns = SCHEMAS[group]
        path = out_dir / f"{safe_name(source)}_{group}.csv"
        write_csv(path, rows, columns)
        if rows:
            written.append(path)
            print(f"normalized {len(rows)} rows -> {path}", flush=True)

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Build canonical per-source product CSVs for cleaning and raw loading.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument(
        "--max-rows",
        type=int,
        default=int(os.environ.get("NORMALIZED_MAX_ROWS") or os.environ.get("PARSER_MAX_ROWS") or "15000"),
        help="Max rows per normalized source/category file. 0 means unlimited.",
    )
    parser.add_argument(
        "--sources",
        default="",
        help="Comma-separated sources to normalize: f7,shinline,fdrive,almatyres,carcity,pitstopshop,satu,forte_market.",
    )
    args = parser.parse_args()
    sources = {item.strip() for item in args.sources.split(",") if item.strip()} or None
    written = normalize(Path(args.data_dir), max_rows=args.max_rows, sources=sources)
    print(f"done. normalized_files={len(written)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
