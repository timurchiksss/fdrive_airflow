#!/usr/bin/env python3
"""Автономный парсер carcity.kz.

Файл не зависит от ``parsers/code for parser`` и подходит для:

1. Ручного теста:
   python3 parsers/carcity.py --categories tires --limit 20 -v

2. Полного запуска:
   python3 parsers/carcity.py --categories all --workers 6

3. Airflow DAG:
   from parsers.carcity import run_carcity_parser
   run_carcity_parser(output_dir="/project/data/carcity", per_group=150)

Результаты:
  carcity_tires.csv          - шины, схема согласована с FDrive;
  carcity_oils.csv           - масла, схема согласована с FDrive;
  carcity_filters.csv        - фильтры;
  carcity_batteries.csv      - аккумуляторы;
  carcity_price_history.csv  - история минимальной цены товара;
  state.sqlite               - состояние для истории и режима --resume.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


log = logging.getLogger("carcity")

SOURCE = "carcity"
BASE_URL = "https://carcity.kz"
API_CATEGORY_URL = BASE_URL + "/api/bff/api/catalog/product/{slug}"
USER_AGENT = "FreedomHolding-SDU-Catalog-Bot/1.0 (+master-data-catalog research)"
DEFAULT_CURRENCY = "KZT"
DEFAULT_PER_PAGE = 500
API_MAX_PER_PAGE = 24
DEFAULT_WORKERS = 6
DEFAULT_MIN_DELAY = 0.3
REQUEST_TIMEOUT = 30
MAX_RETRIES = 4
MAX_PAGES = 400

CATEGORY_GROUPS = ("tires", "oils", "filters", "batteries")
CATEGORIES: dict[str, list[str]] = {
    "tires": [
        "siny-letnie",
        "siny-zimnie",
        "siny-dlia-kommerceskogo-transporta",
        "siny-dlia-gruzovogo-transporta",
        "motosiny",
        "siny",
    ],
    "oils": [
        "motornye-masla",
        "avtomobilnye-motornye-masla",
        "motornye-masla-dlia-mototexniki",
        "motornye-masla-dlia-lodocnyx-motorov",
        "transmissionnye-masla",
        "specialnye-masla",
    ],
    "filters": [
        "maslianye-filtry",
        "vozdusnye-filtry",
        "salonnye-filtry",
        "toplivnye-filtry",
        "transmissionnye-filtry",
        "gidravliceskie-filtry",
    ],
    "batteries": ["akkumuliatornye-batarei"],
}

GROUP_ALIASES = {
    "tires": "tires",
    "tire": "tires",
    "tyre": "tires",
    "шины": "tires",
    "шина": "tires",
    "oils": "oils",
    "oil": "oils",
    "масла": "oils",
    "масло": "oils",
    "filters": "filters",
    "filter": "filters",
    "фильтры": "filters",
    "фильтр": "filters",
    "batteries": "batteries",
    "battery": "batteries",
    "акб": "batteries",
    "аккумуляторы": "batteries",
}

GROUP_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("filters", ("filtr", "фильтр")),
    ("tires", ("siny", "shin", "шин", "покрышк")),
    ("batteries", ("akkum", "akb", "аккум", "акб")),
    ("oils", ("masla", "maslo", "масл", "avtoximi", "автохими")),
]

ATTRS_BY_GROUP: dict[str, list[str]] = {
    "tires": [
        "tire_width",
        "tire_profile",
        "tire_diameter",
        "season",
        "load_index",
        "speed_index",
        "runflat",
        "studded",
        "model_name",
        "tire_type",
        "tread_pattern",
        "offroad_marking",
        "set_configuration",
        "brand_country",
        "reinforced",
    ],
    "oils": [
        "viscosity",
        "volume_liters",
        "oil_type",
        "engine_type",
        "specification",
        "product_line",
        "package_type",
        "atf_standard",
        "transmission_type",
        "hypoid",
    ],
    "filters": ["filter_type", "manufacturer_article"],
    "batteries": [
        "capacity_ah",
        "voltage_v",
        "start_current_a",
        "polarity",
        "battery_type",
        "dimensions",
        "terminal_type",
        "case_type",
    ],
}

CROSS_ATTRS = [
    "purpose",
    "features",
    "weight",
    "compatible_brand",
    "compatible_model",
    "compatible_years",
]
GROUP_OUTPUT_COLUMNS: dict[str, list[str]] = {
    "tires": [
        "product_id",
        "name",
        "price",
        "url",
        "slug",
        "images",
        "brand",
        "season",
        "size",
        "width",
        "height",
        "diameter",
        "weight_single_index",
        "weight_double_index",
        "velocity_index",
        "quantity_available",
        "tyre_auto_type_name",
        "tyre_stud_type_name",
        "is_ecar",
        "article_sku",
        "rating",
        "reviews_count",
        "seller_count",
        "model_name",
        "weight",
    ],
    "oils": [
        "product_id",
        "name",
        "price",
        "url",
        "slug",
        "category",
        "brand_name",
        "images",
        "Вид масла",
        "Класс API",
        "Класс вязкости SAE",
        "Объем упаковки, л",
        "Область применения",
        "Тип коробки передач",
        "Назначение",
        "Упаковка",
        "Класс ACEA",
        "Допуски",
        "Тип двигателя",
        "article_sku",
        "rating",
        "reviews_count",
        "seller_count",
    ],
    "filters": [
        "product_id",
        "name",
        "price",
        "url",
        "slug",
        "category",
        "brand",
        "images",
        "quantity_available",
        "filter_type",
        "manufacturer_article",
        "compatible_brand",
        "compatible_model",
        "compatible_years",
        "oem_numbers",
        "additional_information",
        "article_sku",
        "rating",
        "reviews_count",
        "seller_count",
    ],
    "batteries": [
        "product_id",
        "name",
        "price",
        "url",
        "slug",
        "category",
        "brand",
        "images",
        "quantity_available",
        "capacity_ah",
        "voltage_v",
        "start_current_a",
        "polarity",
        "battery_type",
        "dimensions",
        "terminal_type",
        "case_type",
        "weight",
        "features",
        "length",
        "width",
        "height",
        "article_sku",
        "rating",
        "reviews_count",
        "seller_count",
    ],
}
PRICE_HISTORY_COLUMNS = [
    "parsed_at", "price_date", "source", "product_id", "price",
    "quantity_available",
]

PRODUCT_HREF_RE = re.compile(r'href="(/product/[a-z0-9\-]+?-\d+)(?:\?[^"]*)?"')
ID_RE = re.compile(r"-(\d+)$")
NUXT_RE = re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)
CHAR_RE = re.compile(
    r'"([^"\\]{2,40})"\s*,\s*\d+\s*,\s*\[([\d,\s]*)\]'
    r'((?:\s*,\s*"[^"\\]{0,90}")+)'
)
QUOTED_RE = re.compile(r'"([^"\\]{0,90})"')
PRICE_RE = re.compile(r"\d[\d\s ]*\d|\d")
PREORDER_RE = re.compile(r"Предзаказ:\s*\+?(\d+)\s*дн")
TIRE_RE = re.compile(
    r"(?P<w>\d{3})\s*[/x]\s*(?P<p>\d{2,3})\s*"
    r"[RrZzДд]+\s*(?P<d>\d{2}(?:[.,]\d)?)"
    r"(?:\s+(?P<load>\d{2,3})\s*(?P<speed>[A-Za-z]{1,2})\b)?",
    re.IGNORECASE,
)
RUNFLAT_RE = re.compile(
    r"(run[\s-]?flat|\brft\b|\brof\b|\bssr\b|\bzp\b|\bdsst\b|"
    r"\bhrs\b|\brun[\s-]?on[\s-]?flat\b)",
    re.IGNORECASE,
)
VISCOSITY_RE = re.compile(r"\b(\d{1,2})\s*[Ww]\s*-?\s*(\d{2})\b")
VISCOSITY_MONO_RE = re.compile(r"\bSAE\s*(\d{1,3}W?)\b", re.IGNORECASE)
ML_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:мл|ml)\b", re.IGNORECASE)
LITER_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:литр\w*|л|l)\b", re.IGNORECASE)
SYN_NAME_RE = re.compile(r"\b(syn|synergie|synth|синт)\b", re.IGNORECASE)
CAPACITY_RE = re.compile(r"(\d{2,3})\s*(?:а[·.]?ч|ah|ампер[\s-]?час)", re.IGNORECASE)
CAPACITY_GOST_RE = re.compile(r"6\s*СТ\s*-\s*(\d{2,3})", re.IGNORECASE)
VOLTAGE_RE = re.compile(r"\b(6|12|24)\s*(?:в|v|вольт)\b", re.IGNORECASE)
BAD_VALUES = {"", "отсутствует", "нет данных", "-", "—", "не указано"}
PHYSICAL_KEYS = ("weight", "length", "width", "height")


@dataclass
class Offer:
    seller_name: str = ""
    price: float | None = None
    old_price: float | None = None
    currency: str = DEFAULT_CURRENCY
    availability: str = ""
    quantity_in_stock: int | None = None
    delivery_days: int | None = None
    city: str = ""


@dataclass
class Product:
    source: str
    source_product_id: str
    source_url: str
    name: str = ""
    brand: str = ""
    article_sku: str = ""
    category_group: str = ""
    category_l1: str = ""
    category_leaf: str = ""
    oem_numbers: list[str] = field(default_factory=list)
    image_url: str = ""
    rating: float | None = None
    reviews_count: int | None = None
    attributes: dict[str, object] = field(default_factory=dict)
    offers: list[Offer] = field(default_factory=list)
    parsed_at: str = ""

    def fingerprint(self) -> str:
        payload = {
            "name": self.name,
            "brand": self.brand,
            "rating": self.rating,
            "reviews_count": self.reviews_count,
            "attributes": {
                key: self.attributes.get(key)
                for key in sorted(self.attributes)
            },
            "offers": sorted(
                (offer.seller_name, offer.price, offer.old_price, offer.availability)
                for offer in self.offers
            ),
        }
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def output_row(self) -> dict[str, object]:
        prices = [offer.price for offer in self.offers if offer.price is not None]
        quantities = [
            offer.quantity_in_stock
            for offer in self.offers
            if offer.quantity_in_stock is not None
        ]
        price: object = min(prices) if prices else ""
        quantity: object = sum(quantities) if quantities else ""
        slug = urlsplit(self.source_url).path.rstrip("/").rsplit("/", 1)[-1]
        base: dict[str, object] = {
            "product_id": self.source_product_id,
            "name": self.name,
            "price": price,
            "url": self.source_url,
            "slug": slug,
            "category": self.category_leaf or self.category_l1,
            "brand": self.brand,
            "brand_name": self.brand,
            "images": self.image_url,
            "quantity_available": quantity,
            "article_sku": self.article_sku,
            "rating": self.rating if self.rating is not None else "",
            "reviews_count": (
                self.reviews_count if self.reviews_count is not None else ""
            ),
            "seller_count": len(self.offers),
        }

        if self.category_group == "tires":
            width = self.attributes.get("tire_width", "")
            height = self.attributes.get("tire_profile", "")
            diameter = self.attributes.get("tire_diameter", "")
            size = ""
            if width and height and diameter:
                size = f"{width}/{height} R{diameter}"
            season_map = {
                "Летняя": "summer",
                "Зимняя": "winter",
                "Всесезонная": "all_season",
            }
            studded = self.attributes.get("studded")
            stud_type = (
                "studded" if studded is True
                else "studless" if studded is False
                else ""
            )
            base.update(
                {
                    "season": season_map.get(
                        str(self.attributes.get("season") or ""),
                        self.attributes.get("season", ""),
                    ),
                    "size": size,
                    "width": width,
                    "height": height,
                    "diameter": diameter,
                    "weight_single_index": self.attributes.get("load_index", ""),
                    "weight_double_index": "",
                    "velocity_index": self.attributes.get("speed_index", ""),
                    "tyre_auto_type_name": self.attributes.get("tire_type", ""),
                    "tyre_stud_type_name": stud_type,
                    "is_ecar": "",
                    "model_name": self.attributes.get("model_name", ""),
                    "weight": self.attributes.get("weight", ""),
                }
            )
        elif self.category_group == "oils":
            base.update(
                {
                    "Вид масла": self.attributes.get("oil_type", ""),
                    "Класс API": self.attributes.get("specification", ""),
                    "Класс вязкости SAE": self.attributes.get("viscosity", ""),
                    "Объем упаковки, л": self.attributes.get("volume_liters", ""),
                    "Область применения": self.attributes.get("engine_type", ""),
                    "Тип коробки передач": self.attributes.get("transmission_type", ""),
                    "Назначение": self.attributes.get("purpose", ""),
                    "Упаковка": self.attributes.get("package_type", ""),
                    "Класс ACEA": self.attributes.get("acea_class", ""),
                    "Допуски": self.attributes.get("approvals", ""),
                    "Тип двигателя": self.attributes.get("engine_type", ""),
                }
            )
        elif self.category_group == "filters":
            base.update(
                {
                    "filter_type": self.attributes.get("filter_type", ""),
                    "manufacturer_article": self.attributes.get(
                        "manufacturer_article", ""
                    ),
                    "compatible_brand": self.attributes.get(
                        "compatible_brand", ""
                    ),
                    "compatible_model": self.attributes.get(
                        "compatible_model", ""
                    ),
                    "compatible_years": self.attributes.get(
                        "compatible_years", ""
                    ),
                    "oem_numbers": "; ".join(self.oem_numbers),
                    "additional_information": self.attributes.get(
                        "additional_information", ""
                    ),
                }
            )
        elif self.category_group == "batteries":
            for column in GROUP_OUTPUT_COLUMNS["batteries"]:
                if column not in base:
                    base[column] = self.attributes.get(column, "")
        else:
            for column in GROUP_OUTPUT_COLUMNS.get(self.category_group, []):
                if column not in base:
                    base[column] = self.attributes.get(column, "")
        return base


@dataclass
class RunSummary:
    discovered: int
    processed: int
    products: int
    rows_written: int
    rows_by_group: dict[str, int]
    history_rows_written: int
    skipped: int
    errors: int
    output_files: dict[str, str]
    history_csv: str
    state_db: str
    elapsed_seconds: float
    new: int
    changed: int
    unchanged: int

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


def product_id(path_or_url: str) -> str:
    match = ID_RE.search(path_or_url)
    return match.group(1) if match else path_or_url.rstrip("/").rsplit("/", 1)[-1]


def progress(message: str) -> None:
    """Печатать прогресс сразу, в том числе в логах Airflow."""
    print(f"[carcity] {message}", flush=True)


def make_soup(html: str) -> BeautifulSoup:
    """Создать HTML-дерево без обязательной зависимости от lxml."""
    return BeautifulSoup(html, "html.parser")


def parse_groups(value: str | Iterable[str] | None) -> set[str]:
    if value is None:
        return set(CATEGORY_GROUPS)
    tokens = value.split(",") if isinstance(value, str) else value
    cleaned = [str(token).strip().lower() for token in tokens if str(token).strip()]
    if not cleaned or cleaned == ["all"]:
        return set(CATEGORY_GROUPS)
    groups: set[str] = set()
    for token in cleaned:
        if token not in GROUP_ALIASES:
            raise ValueError(f"Неизвестная категория Carcity: {token!r}")
        groups.add(GROUP_ALIASES[token])
    return groups


def classify_category(text: str) -> str | None:
    low = (text or "").lower()
    for group, keywords in GROUP_KEYWORDS:
        if any(keyword in low for keyword in keywords):
            return group
    return None


def parse_price(text: str | None) -> float | None:
    if not text:
        return None
    match = PRICE_RE.search(text)
    if not match:
        return None
    digits = re.sub(r"[\s ]", "", match.group(0))
    return float(digits) if digits.isdigit() else None


def parse_tire_size(text: str | None) -> dict[str, object]:
    empty: dict[str, object] = {
        "tire_width": None,
        "tire_profile": None,
        "tire_diameter": None,
        "load_index": "",
        "speed_index": "",
    }
    match = TIRE_RE.search(text or "")
    if not match:
        return empty
    diameter: int | float = float(match.group("d").replace(",", "."))
    if float(diameter).is_integer():
        diameter = int(diameter)
    return {
        "tire_width": int(match.group("w")),
        "tire_profile": int(match.group("p")),
        "tire_diameter": diameter,
        "load_index": match.group("load") or "",
        "speed_index": (match.group("speed") or "").upper(),
    }


def detect_season(text: str | None) -> str:
    low = (text or "").lower()
    season_keywords = [
        ("Всесезонная", ("всесезон", "vsesezon", "all season", "all-season", "all weather", "a/s")),
        ("Зимняя", ("зимн", "зим", "zimn", "winter", "шип", "ice", "snow", "frost")),
        ("Летняя", ("летн", "letn", "summer")),
    ]
    for label, keywords in season_keywords:
        if any(keyword in low for keyword in keywords):
            return label
    return ""


def detect_runflat(text: str | None) -> bool:
    return bool(RUNFLAT_RE.search(text or ""))


def parse_studded(text: str | None) -> bool | None:
    low = (text or "").lower()
    if not low:
        return None
    if any(marker in low for marker in ("без шип", "нешип", "липучк", "фрикцион")):
        return False
    return True if "шип" in low else None


def parse_viscosity(text: str | None) -> str:
    match = VISCOSITY_RE.search(text or "")
    if match:
        return f"{int(match.group(1))}W-{match.group(2)}"
    match = VISCOSITY_MONO_RE.search(text or "")
    return f"SAE {match.group(1).upper()}" if match else ""


def parse_volume_liters(text: str | None) -> float | None:
    match = ML_RE.search(text or "")
    if match:
        return round(float(match.group(1).replace(",", ".")) / 1000, 4)
    match = LITER_RE.search(text or "")
    return float(match.group(1).replace(",", ".")) if match else None


def detect_oil_type(text: str | None) -> str:
    low = (text or "").lower()
    if "полусинт" in low or "semi" in low:
        return "Полусинтетическое"
    if any(marker in low for marker in ("гидрокрекинг", "hc-synth", "hydrocrack")):
        return "Гидрокрекинговое"
    if "синтет" in low or "synthetic" in low:
        return "Синтетическое"
    if "минерал" in low or "mineral" in low:
        return "Минеральное"
    return "Синтетическое" if SYN_NAME_RE.search(text or "") else ""


def parse_capacity_ah(text: str | None) -> int | None:
    match = CAPACITY_RE.search(text or "") or CAPACITY_GOST_RE.search(text or "")
    return int(match.group(1)) if match else None


def parse_voltage_v(text: str | None) -> int | None:
    match = VOLTAGE_RE.search(text or "")
    return int(match.group(1)) if match else None


def detect_battery_polarity(text: str | None) -> str:
    low = (text or "").lower()
    if "обратн" in low or "правый" in low or "правая" in low:
        return "Обратная"
    if "прям" in low or "левый" in low or "левая" in low:
        return "Прямая"
    if re.search(r"(?:^|\s)-\+(?:\s|$)", low):
        return "Обратная"
    if re.search(r"(?:^|\s)\+-(?:\s|$)", low):
        return "Прямая"
    return ""


def detect_filter_type(text: str | None) -> str:
    low = (text or "").lower()
    for keyword, label in (
        ("масл", "Масляный"),
        ("воздуш", "Воздушный"),
        ("топлив", "Топливный"),
        ("салон", "Салонный"),
        ("гидравл", "Гидравлический"),
        ("трансмисс", "Трансмиссионный"),
    ):
        if keyword in low:
            return label
    return ""


def carcity_availability(text: str | None, default: str = "В наличии") -> str:
    days = [int(value) for value in PREORDER_RE.findall(text or "")]
    if not days:
        return default
    best = min(days)
    return "В наличии" if best == 0 else f"Под заказ: {best} дн"


def availability_from_days(days: int | None) -> str:
    if days in (None, 0):
        return "В наличии"
    return f"Под заказ: {days} дн"


def first_number(value: str | None) -> float | None:
    match = re.search(r"-?\d+(?:[.,]\d+)?", value or "")
    return float(match.group().replace(",", ".")) if match else None


def attributes_from_chars(group: str, chars: dict[str, list[str]]) -> dict[str, object]:
    def first(*keys: str) -> str:
        for key in keys:
            values = chars.get(key)
            if values:
                value = str(values[0]).strip()
                if value.lower() not in BAD_VALUES:
                    return value
        return ""

    def joined(*keys: str) -> str:
        for key in keys:
            values = chars.get(key)
            if values:
                clean = [
                    str(value).strip()
                    for value in values
                    if str(value).strip().lower() not in BAD_VALUES
                ]
                if clean:
                    return "; ".join(dict.fromkeys(clean))
        return ""

    out: dict[str, object] = {}
    for column, keys in (
        ("purpose", ("Назначение",)),
        ("features", ("Особенности",)),
        ("weight", ("Вес", "Вес (гр)", "Вес, кг", "Вес, г", "Масса")),
        ("compatible_brand", ("Марка автомобиля", "Марка авто", "Совместимая марка")),
        ("compatible_model", ("Модель автомобиля", "Совместимая модель")),
        ("compatible_years", ("Год выпуска автомобиля", "Год выпуска")),
    ):
        value = (
            joined(*keys)
            if column.startswith("compatible_") or column == "features"
            else first(*keys)
        )
        if value:
            out[column] = value

    if group == "tires":
        width = first_number(first("Ширина профиля"))
        profile = first_number(first("Высота профиля"))
        diameter = first_number(first("Диаметр диска", "Посадочный диаметр", "Диаметр"))
        if width:
            out["tire_width"] = int(width)
        if profile:
            out["tire_profile"] = int(profile)
        if diameter is not None:
            out["tire_diameter"] = int(diameter) if diameter.is_integer() else diameter
        if match := re.match(r"\s*(\d+)", first("Индекс нагрузки")):
            out["load_index"] = match.group(1)
        if match := re.search(r"[A-Za-z]{1,2}", first("Индекс скорости")):
            out["speed_index"] = match.group(0).upper()
        if season := detect_season(first("Сезонность", "Сезон")):
            out["season"] = season
        if studs := first("Шипы").lower():
            out["studded"] = "шип" in studs and "без" not in studs
        if runflat := first("Run Flat", "RunFlat", "Технология RunFlat").lower():
            out["runflat"] = runflat in ("да", "есть", "yes", "true") or "run" in runflat
        for column, keys in (
            ("model_name", ("Название модели",)),
            ("tire_type", ("Тип шины",)),
            ("tread_pattern", ("Тип рисунка протектора", "Направленный рисунок протектора", "Рисунок протектора")),
            ("offroad_marking", ("Маркировка внедорожных шин",)),
            ("set_configuration", ("Комплектация",)),
        ):
            if value := first(*keys):
                out[column] = value
    elif group == "oils":
        if value := detect_oil_type(first("Вид масла", "Тип масла", "Основа масла")):
            out["oil_type"] = value
        if value := parse_viscosity(first("Класс вязкости SAE", "Вязкость по SAE", "Вязкость", "Вязкость SAE")):
            out["viscosity"] = value
        if value := first_number(first("Объем", "Объём", "Объем, л")):
            out["volume_liters"] = value
        if value := joined("Класс ACEA"):
            out["acea_class"] = value
        if value := joined("Допуски", "Допуск"):
            out["approvals"] = value
        for column, keys in (
            ("engine_type", ("Тип двигателя",)),
            ("specification", ("Допуски", "Класс API", "Класс ACEA", "Спецификация")),
            ("product_line", ("Линейка", "Серия", "Семейство")),
            ("package_type", ("Тип упаковки", "Тип тары", "Вид тары", "Упаковка")),
            ("atf_standard", ("Стандарт ATF",)),
            ("transmission_type", ("Тип коробки передач",)),
            ("hypoid", ("Гипоидное масло",)),
        ):
            if value := first(*keys):
                out[column] = value
    elif group == "batteries":
        if value := first_number(first("Емкость", "Ёмкость", "Емкость АКБ")):
            out["capacity_ah"] = int(value)
        if value := first_number(first("Напряжение")):
            out["voltage_v"] = int(value)
        if value := first_number(first("Пусковой ток")):
            out["start_current_a"] = int(value)
        polarity = first("Полярность").lower()
        if "обратн" in polarity:
            out["polarity"] = "Обратная"
        elif "прям" in polarity:
            out["polarity"] = "Прямая"
        if value := first("Тип", "Тип аккумулятора", "Технология"):
            out["battery_type"] = value
        dimensions = [value for value in (first("Длина"), first("Ширина"), first("Высота")) if value]
        if dimensions:
            out["dimensions"] = " × ".join(dimensions)
        for column, keys in (
            ("length", ("Длина",)),
            ("width", ("Ширина",)),
            ("height", ("Высота",)),
        ):
            if value := first(*keys):
                out[column] = value
        if value := first("Тип клемм", "Клеммы", "Расположение клемм"):
            out["terminal_type"] = value
        if value := first("Тип корпуса"):
            out["case_type"] = value
    elif group == "filters":
        if value := detect_filter_type(first("Тип фильтра", "Тип")):
            out["filter_type"] = value
        if value := first("Артикул производителя", "Артикул"):
            out["manufacturer_article"] = value
        if value := joined("Дополнительная информация"):
            out["additional_information"] = value
    return out


def oem_numbers_from_chars(chars: dict[str, list[str]]) -> list[str]:
    result: list[str] = []
    for key in (
        "Запчасть совместима с ОЕМ",
        "Номер OEM",
        "OEM",
        "OEM номер",
        "Оригинальный номер",
    ):
        for raw_value in chars.get(key, []) or []:
            value = str(raw_value).strip()
            if value and value.lower() not in BAD_VALUES:
                result.append(value)
    return list(dict.fromkeys(result))


def extract_for_group(group: str, name: str, category_text: str = "") -> dict[str, object]:
    blob = f"{name or ''} {category_text or ''}".strip()
    if group == "tires":
        result = parse_tire_size(name)
        result["season"] = detect_season(name) or detect_season(category_text)
        result["runflat"] = detect_runflat(name)
        studded = parse_studded(name)
        if studded is None and result["season"] in ("Летняя", "Всесезонная"):
            studded = False
        result["studded"] = studded
        return result
    if group == "oils":
        return {
            "viscosity": parse_viscosity(blob),
            "volume_liters": parse_volume_liters(blob),
            "oil_type": detect_oil_type(blob),
            "engine_type": "",
            "specification": "",
            "product_line": "",
            "package_type": "",
        }
    if group == "batteries":
        return {
            "capacity_ah": parse_capacity_ah(blob),
            "voltage_v": parse_voltage_v(blob),
            "start_current_a": None,
            "polarity": detect_battery_polarity(blob),
            "battery_type": "",
            "dimensions": "",
            "terminal_type": "",
        }
    if group == "filters":
        return {
            "filter_type": detect_filter_type(category_text) or detect_filter_type(name),
            "compatible_brand": "",
            "compatible_model": "",
        }
    return {}


def parse_nuxt_data(html: str) -> list[Any]:
    match = NUXT_RE.search(html or "")
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def deref(
    values: list[Any],
    index: Any,
    depth: int = 0,
    seen: tuple[int, ...] = (),
) -> Any:
    if (
        not isinstance(index, int)
        or index < 0
        or index >= len(values)
        or index in seen
        or depth > 6
    ):
        return index
    value = values[index]
    next_seen = seen + (index,)
    if isinstance(value, dict):
        return {
            key: deref(values, child, depth + 1, next_seen)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [deref(values, child, depth + 1, next_seen) for child in value[:20]]
    return value


def find_offers(values: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for element in values:
        if not (
            isinstance(element, dict)
            and "company" in element
            and "price" in element
            and "quantity_in_stock" in element
        ):
            continue
        offer = {key: deref(values, value) for key, value in element.items()}
        company = offer.get("company")
        seller = company.get("name") if isinstance(company, dict) else company
        price = offer.get("price")
        price_per_unit = price.get("per_unit") if isinstance(price, dict) else price
        if not seller or (seller, price_per_unit) in seen:
            continue
        seen.add((seller, price_per_unit))
        result.append(
            {
                "seller": seller,
                "price": price_per_unit,
                "delivery_days": offer.get("delivery_days"),
                "quantity_in_stock": offer.get("quantity_in_stock"),
            }
        )
    return result


def physical_fields(values: list[Any], name: str = "") -> dict[str, int | float]:
    best: dict[str, Any] | None = None
    best_score = -1
    for element in values:
        if not (
            isinstance(element, dict)
            and "offers" in element
            and "slug" in element
            and all(key in element for key in PHYSICAL_KEYS)
        ):
            continue
        score = len(element)
        resolved_name = deref(values, element.get("name"))
        if name and isinstance(resolved_name, str) and resolved_name.strip() == name.strip():
            score += 10_000
        if score > best_score:
            best = element
            best_score = score
    if best is None:
        return {}

    result: dict[str, int | float] = {}
    for key in PHYSICAL_KEYS:
        value = deref(values, best.get(key))
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value > 0:
            result[key] = int(value) if float(value).is_integer() else value
    return result


def characteristics(html: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for match in CHAR_RE.finditer(html or ""):
        name = match.group(1)
        indexes = [value for value in match.group(2).split(",") if value.strip()]
        count = max(1, len(indexes))
        values = [
            value
            for value in QUOTED_RE.findall(match.group(3))[:count]
            if value
        ]
        if values and name not in result:
            result[name] = values
    return result


def compile_robots_pattern(pattern: str) -> re.Pattern[str]:
    anchored_end = pattern.endswith("$")
    if anchored_end:
        pattern = pattern[:-1]
    parts = ["^"]
    for character in pattern:
        parts.append(".*" if character == "*" else re.escape(character))
    if anchored_end:
        parts.append("$")
    return re.compile("".join(parts))


class RobotsRules:
    def __init__(self) -> None:
        self.rules: list[tuple[int, bool, re.Pattern[str]]] = []
        self.crawl_delay: float | None = None

    @classmethod
    def parse(cls, text: str, user_agent: str) -> "RobotsRules":
        user_agent_token = user_agent.split("/", 1)[0].lower()
        groups: dict[str, list[tuple[str, str]]] = {}
        delays: dict[str, float] = {}
        current: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field_name, _, value = line.partition(":")
            field_name = field_name.strip().lower()
            value = value.strip()
            if field_name == "user-agent":
                current = [value.lower()]
                groups.setdefault(value.lower(), [])
            elif field_name in ("allow", "disallow") and current:
                for user_agent_name in current:
                    groups.setdefault(user_agent_name, []).append((field_name, value))
            elif field_name == "crawl-delay" and current:
                try:
                    for user_agent_name in current:
                        delays[user_agent_name] = float(value)
                except ValueError:
                    pass

        selected = next(
            (
                group
                for group in groups
                if group != "*" and group and group in user_agent_token
            ),
            "*" if "*" in groups else None,
        )
        parsed = cls()
        if selected is not None:
            for field_name, value in groups.get(selected, []):
                if not value and field_name == "disallow":
                    continue
                parsed.rules.append(
                    (
                        len(value),
                        field_name == "allow",
                        compile_robots_pattern(value),
                    )
                )
            parsed.crawl_delay = delays.get(selected)
        return parsed

    def allowed(self, url: str) -> bool:
        path = unquote(urlsplit(url).path or "/")
        best_length = -1
        best_allow = True
        for length, allow, pattern in self.rules:
            if pattern.match(path) and (
                length > best_length or (length == best_length and allow)
            ):
                best_length = length
                best_allow = allow
        return best_allow


class Fetcher:
    def __init__(
        self,
        *,
        user_agent: str = USER_AGENT,
        min_delay: float = DEFAULT_MIN_DELAY,
        timeout: int = REQUEST_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        respect_robots: bool = True,
    ) -> None:
        self.user_agent = user_agent
        self.min_delay = min_delay
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.session = requests.Session()
        retries = Retry(
            total=max_retries,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "ru,en;q=0.8",
                "City-Id": "1",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        self.lock = threading.Lock()
        self.last_request: dict[str, float] = {}
        self.robots: dict[str, RobotsRules] = {}

    def robots_for(self, url: str) -> RobotsRules:
        host = urlsplit(url).netloc
        with self.lock:
            cached = self.robots.get(host)
        if cached is not None:
            return cached
        parts = urlsplit(url)
        try:
            response = self.session.get(
                f"{parts.scheme}://{host}/robots.txt",
                timeout=self.timeout,
            )
            text = response.text if response.status_code == 200 else ""
            progress(
                f"robots.txt: HTTP {response.status_code}, "
                f"{len(response.content)} байт"
            )
        except requests.RequestException as exc:
            progress(f"robots.txt не удалось загрузить: {exc}")
            text = ""
        rules = RobotsRules.parse(text, self.user_agent)
        with self.lock:
            self.robots[host] = rules
        return rules

    def get(self, url: str) -> requests.Response | None:
        rules = self.robots_for(url) if self.respect_robots else None
        if rules is not None and not rules.allowed(url):
            log.warning("robots.txt запрещает: %s", url)
            progress(f"ЗАПРЕЩЕНО robots.txt: {url}")
            return None
        delay = max(
            self.min_delay,
            float(rules.crawl_delay or 0) if rules is not None else 0,
        )
        host = urlsplit(url).netloc
        with self.lock:
            wait = delay - (time.monotonic() - self.last_request.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            self.last_request[host] = time.monotonic()
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response


class CarCityScraper:
    def __init__(
        self,
        fetcher: Fetcher | None = None,
        *,
        per_page: int = DEFAULT_PER_PAGE,
        max_pages: int = MAX_PAGES,
    ) -> None:
        self.fetcher = fetcher or Fetcher()
        self.per_page = per_page
        self.max_pages = max_pages
        self.listing_metadata: dict[str, dict[str, object]] = {}

    def target_categories(self, groups: set[str]) -> list[tuple[str, str, str]]:
        result: list[tuple[str, str, str]] = []
        for group in CATEGORY_GROUPS:
            if group not in groups:
                continue
            for slug in CATEGORIES[group]:
                result.append((f"{BASE_URL}/category/{slug}", group, slug))
        return result

    @staticmethod
    def extract_product_paths(html: str) -> list[str]:
        """Извлечь product URL строгим regex и резервно через BeautifulSoup."""
        paths = list(dict.fromkeys(PRODUCT_HREF_RE.findall(html)))
        if paths:
            return paths

        soup = make_soup(html)
        result: list[str] = []
        for tag in soup.select('a[href*="/product/"]'):
            href = str(tag.get("href") or "").strip()
            if not href:
                continue
            path = urlsplit(href).path
            if path.startswith("/product/") and ID_RE.search(path):
                result.append(path.rstrip("/"))
        return list(dict.fromkeys(result))

    def product_urls_from_api(
        self,
        category_url: str,
        max_items: int | None = None,
    ) -> list[str]:
        slug = category_url.rstrip("/").rsplit("/", 1)[-1]
        api_url = API_CATEGORY_URL.format(slug=slug)
        api_page_size = min(self.per_page, API_MAX_PER_PAGE)
        urls: list[str] = []
        seen_ids: set[str] = set()

        progress(
            f"Использую BFF API категории: {api_url}, "
            f"товаров на страницу={api_page_size}"
        )
        for page in range(1, self.max_pages + 1):
            progress(f"Загружаю API: категория={slug}, страница={page}")
            try:
                response = self.fetcher.get(
                    f"{api_url}?per_page={api_page_size}&page={page}"
                )
                if response is None:
                    progress("API не получен")
                    break
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                progress(f"ОШИБКА API: {type(exc).__name__}: {exc}")
                break

            data = payload.get("data") if isinstance(payload, dict) else {}
            data = data if isinstance(data, dict) else {}
            items = data.get("items") or []
            pagination = data.get("pagination") or {}
            new_count = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "")
                product_url = str(item.get("url") or "")
                if not product_url and item.get("seo_path"):
                    product_url = f"{BASE_URL}/product/{item['seo_path']}"
                if not item_id or not product_url or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                urls.append(product_url)
                review_stats = item.get("review_stats") or {}
                self.listing_metadata[product_url] = {
                    "rating": (
                        review_stats.get("average_rating")
                        if isinstance(review_stats, dict)
                        else None
                    ),
                    "reviews_count": (
                        review_stats.get("total")
                        if isinstance(review_stats, dict)
                        else None
                    ),
                }
                new_count += 1
                if max_items and len(urls) >= max_items:
                    break

            total = int(pagination.get("total") or len(urls))
            last_page = int(pagination.get("last_page") or page)
            progress(
                f"API страница {page}/{last_page}: HTTP {response.status_code}, "
                f"получено={len(items)}, новых={new_count}, "
                f"в категории={len(urls)}/{total}"
            )
            if (
                not items
                or new_count == 0
                or page >= last_page
                or (max_items and len(urls) >= max_items)
            ):
                break

        progress(f"Итог API категории {slug}: найдено {len(urls)} URL")
        return urls

    def product_urls_in_category(
        self,
        category_url: str,
        max_items: int | None = None,
    ) -> list[str]:
        if not self.fetcher.respect_robots:
            return self.product_urls_from_api(category_url, max_items=max_items)

        urls: list[str] = []
        seen_ids: set[str] = set()
        for page in range(1, self.max_pages + 1):
            url = f"{category_url}?per_page={self.per_page}&page={page}"
            progress(f"Загружаю листинг: {url}")
            try:
                response = self.fetcher.get(url)
            except requests.RequestException as exc:
                progress(f"ОШИБКА HTTP листинга: {exc}")
                break
            if response is None:
                progress("Листинг не получен: запрос заблокирован robots.txt")
                break

            content_type = response.headers.get("Content-Type", "не указан")
            paths = self.extract_product_paths(response.text)
            new_count = 0
            for path in paths:
                item_id = product_id(path)
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                urls.append(BASE_URL + path)
                new_count += 1
                if max_items and len(urls) >= max_items:
                    break
            progress(
                f"Страница {page}: HTTP {response.status_code}, "
                f"final_url={response.url}, размер={len(response.content)} байт, "
                f"Content-Type={content_type}, ссылок={len(paths)}, "
                f"новых={new_count}, всего в категории={len(urls)}"
            )
            if max_items and len(urls) >= max_items:
                break
            if new_count == 0:
                title = ""
                try:
                    soup = make_soup(response.text)
                    title = soup.title.get_text(" ", strip=True) if soup.title else ""
                except Exception:  # noqa: BLE001
                    pass
                product_mentions = response.text.lower().count("/product/")
                progress(
                    "Останавливаю категорию: новые ссылки не найдены. "
                    f"title={title!r}, упоминаний '/product/'={product_mentions}. "
                    "Возможные причины: изменилась разметка, редирект, "
                    "страница защиты или категория пуста."
                )
                progress(
                    "Текущий Carcity загружает товары через /api/bff/, "
                    "но robots.txt не разрешает /api/. Для ручного запуска API "
                    "используйте флаг --no-robots."
                )
                break
        progress(f"Итог категории {category_url}: найдено {len(urls)} URL")
        return urls

    def discover(
        self,
        groups: set[str],
        *,
        limit: int | None = None,
        per_group: int | None = None,
        group_limits: dict[str, int | None] | None = None,
    ) -> list[tuple[str, str, str]]:
        result: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        group_count: dict[str, int] = defaultdict(int)
        effective_limits = {
            group: (group_limits or {}).get(group, per_group)
            for group in groups
        }
        targets = self.target_categories(groups)
        progress(f"Категорий в очереди: {len(targets)}")
        for category_index, (category_url, group, slug) in enumerate(targets, 1):
            group_limit = effective_limits.get(group)
            if group_limit and group_count[group] >= group_limit:
                progress(
                    f"[{category_index}/{len(targets)}] Пропускаю {slug}: "
                    f"лимит группы {group} уже достигнут ({group_count[group]})"
                )
                continue
            log.info("Категория %s (%s)", category_url, group)
            progress(
                f"[{category_index}/{len(targets)}] Категория {slug}, "
                f"группа={group}, уже собрано всего={len(result)}"
            )
            remaining_limits = [
                value
                for value in (
                    limit - len(result) if limit else None,
                    group_limit - group_count[group] if group_limit else None,
                )
                if value is not None
            ]
            category_limit = min(remaining_limits) if remaining_limits else None
            category_urls = self.product_urls_in_category(
                category_url,
                max_items=category_limit,
            )
            for product_url in category_urls:
                item_id = product_id(product_url)
                if item_id in seen:
                    continue
                seen.add(item_id)
                result.append((product_url, group, slug))
                group_count[group] += 1
                if limit and len(result) >= limit:
                    progress(f"Достигнут общий лимит: {limit}")
                    return result
                if group_limit and group_count[group] >= group_limit:
                    progress(
                        f"Достигнут лимит группы {group}: {group_limit}"
                    )
                    break
            progress(
                f"После {slug}: всего уникальных={len(result)}, "
                f"в группе {group}={group_count[group]}"
            )
        progress(
            "Discovery завершён: "
            f"всего={len(result)}, по группам={dict(group_count)}"
        )
        return result

    @staticmethod
    def jsonld_nodes(html: str) -> list[dict[str, Any]]:
        soup = make_soup(html)
        nodes: list[dict[str, Any]] = []
        for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(tag.string or tag.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and isinstance(data.get("@graph"), list):
                nodes.extend(data["@graph"])
            elif isinstance(data, list):
                nodes.extend(item for item in data if isinstance(item, dict))
            elif isinstance(data, dict):
                nodes.append(data)
        return nodes

    def parse(
        self,
        url: str,
        group_hint: str = "",
        category_hint: str = "",
    ) -> Product | None:
        response = self.fetcher.get(url)
        if response is None:
            return None
        nodes = self.jsonld_nodes(response.text)
        product_node = next(
            (node for node in nodes if node.get("@type") == "Product"),
            None,
        )
        breadcrumb = next(
            (node for node in nodes if node.get("@type") == "BreadcrumbList"),
            None,
        )
        if not product_node:
            log.warning("Нет JSON-LD Product на %s", url)
            return None

        name = str(product_node.get("name") or "").strip()
        brand_value = product_node.get("brand")
        if isinstance(brand_value, dict):
            brand = str(brand_value.get("name") or "")
        else:
            brand = str(brand_value or "")
        article = str(product_node.get("sku") or "")
        image_value = product_node.get("image") or ""
        image = (
            str(image_value[0])
            if isinstance(image_value, list) and image_value
            else str(image_value)
        )
        aggregate_rating = product_node.get("aggregateRating") or {}
        listing_meta = self.listing_metadata.get(url, {})
        rating: float | None = None
        reviews_count: int | None = None
        if isinstance(aggregate_rating, dict):
            try:
                raw_rating = aggregate_rating.get("ratingValue")
                rating = (
                    float(raw_rating)
                    if raw_rating not in (None, "")
                    else None
                )
            except (TypeError, ValueError):
                rating = None
            try:
                raw_reviews = (
                    aggregate_rating.get("reviewCount")
                    or aggregate_rating.get("ratingCount")
                )
                reviews_count = (
                    int(raw_reviews)
                    if raw_reviews not in (None, "")
                    else None
                )
            except (TypeError, ValueError):
                reviews_count = None
        if rating is None:
            try:
                raw_rating = listing_meta.get("rating")
                rating = (
                    float(raw_rating)
                    if raw_rating not in (None, "")
                    else None
                )
            except (TypeError, ValueError):
                rating = None
        if reviews_count is None:
            try:
                raw_reviews = listing_meta.get("reviews_count")
                reviews_count = (
                    int(raw_reviews)
                    if raw_reviews not in (None, "")
                    else None
                )
            except (TypeError, ValueError):
                reviews_count = None

        category_l1 = ""
        category_leaf = ""
        if breadcrumb:
            items = breadcrumb.get("itemListElement") or []
            names = [
                str(item.get("name") or "")
                for item in items
                if isinstance(item, dict)
            ]
            if len(names) >= 2:
                category_l1 = names[1]
                category_leaf = names[-2]
        if "(выкл" in category_leaf.lower():
            return None
        group = (
            classify_category(category_leaf)
            or classify_category(category_l1)
            or group_hint
        )

        nuxt_values = parse_nuxt_data(response.text)
        offers: list[Offer] = []
        for raw_offer in find_offers(nuxt_values):
            raw_price = raw_offer.get("price")
            try:
                price = float(raw_price) if raw_price not in (None, "") else None
            except (TypeError, ValueError):
                price = parse_price(str(raw_price))
            delivery_days = raw_offer.get("delivery_days")
            try:
                delivery_days = (
                    int(delivery_days) if delivery_days not in (None, "") else None
                )
            except (TypeError, ValueError):
                delivery_days = None
            quantity = raw_offer.get("quantity_in_stock")
            try:
                quantity = int(quantity) if quantity not in (None, "") else None
            except (TypeError, ValueError):
                quantity = None
            offers.append(
                Offer(
                    seller_name=str(raw_offer.get("seller") or ""),
                    price=price,
                    availability=availability_from_days(delivery_days),
                    quantity_in_stock=quantity,
                    delivery_days=delivery_days,
                )
            )

        if not offers:
            jsonld_offers = product_node.get("offers")
            candidates = jsonld_offers if isinstance(jsonld_offers, list) else [jsonld_offers]
            for raw_offer in candidates:
                if not isinstance(raw_offer, dict):
                    continue
                seller = raw_offer.get("seller") or {}
                raw_price = raw_offer.get("price")
                try:
                    price = float(raw_price) if raw_price not in (None, "") else None
                except (TypeError, ValueError):
                    price = parse_price(str(raw_price))
                offers.append(
                    Offer(
                        seller_name=(
                            str(seller.get("name") or "")
                            if isinstance(seller, dict)
                            else str(seller)
                        ),
                        price=price,
                        currency=str(raw_offer.get("priceCurrency") or DEFAULT_CURRENCY),
                        availability=carcity_availability(response.text),
                    )
                )

        chars = characteristics(response.text)
        category_text = f"{category_l1} {category_leaf} {category_hint}".strip()
        attributes = extract_for_group(group, name, category_text) if group else {}
        if group:
            attributes.update(attributes_from_chars(group, chars))
            physical = physical_fields(nuxt_values, name)
            if physical.get("weight"):
                attributes["weight"] = f"{physical['weight']} г"
            if group == "batteries":
                for key in ("length", "width", "height"):
                    if physical.get(key) and not attributes.get(key):
                        attributes[key] = f"{physical[key]} мм"
            if (
                group == "batteries"
                and not attributes.get("dimensions")
                and all(physical.get(key) for key in ("length", "width", "height"))
            ):
                attributes["dimensions"] = (
                    f"{physical['length']} × {physical['width']} × "
                    f"{physical['height']} мм"
                )

        return Product(
            source=SOURCE,
            source_product_id=product_id(url),
            source_url=url,
            name=name,
            brand=brand,
            article_sku=article,
            category_group=group or "",
            category_l1=category_l1,
            category_leaf=category_leaf,
            oem_numbers=oem_numbers_from_chars(chars),
            image_url=image,
            rating=rating,
            reviews_count=reviews_count,
            attributes=attributes,
            offers=offers,
            parsed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )


class CategoryCsvWriter:
    """Отдельный компактный CSV для каждой товарной группы."""

    def __init__(
        self,
        output_dir: str | Path,
        groups: Iterable[str],
        *,
        append: bool = False,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.files: dict[str, Any] = {}
        self.writers: dict[str, csv.DictWriter] = {}
        self.paths: dict[str, Path] = {}
        group_set = set(groups)
        selected_groups = [
            group for group in CATEGORY_GROUPS if group in group_set
        ]
        self.rows_by_group = {group: 0 for group in selected_groups}
        self.rows_written = 0

        for group in selected_groups:
            path = self.output_dir / f"carcity_{group}.csv"
            existing = append and path.exists() and path.stat().st_size > 0
            file = path.open(
                "a" if existing else "w",
                newline="",
                encoding="utf-8-sig",
            )
            writer = csv.DictWriter(
                file,
                fieldnames=GROUP_OUTPUT_COLUMNS[group],
                extrasaction="ignore",
            )
            if not existing:
                writer.writeheader()
            self.paths[group] = path
            self.files[group] = file
            self.writers[group] = writer

    def write(self, product: Product) -> None:
        group = product.category_group
        writer = self.writers.get(group)
        if writer is None:
            progress(
                f"Пропускаю товар {product.source_product_id}: "
                f"неизвестная группа {group!r}"
            )
            return
        writer.writerow(product.output_row())
        self.rows_by_group[group] += 1
        self.rows_written += 1

    def output_files(self) -> dict[str, str]:
        return {
            group: str(path.resolve())
            for group, path in self.paths.items()
        }

    def __enter__(self) -> "CategoryCsvWriter":
        return self

    def __exit__(self, *_: object) -> None:
        for file in self.files.values():
            file.close()


class PriceHistoryWriter:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size > 0:
            with self.path.open("r", encoding="utf-8-sig", newline="") as source:
                existing_header = next(csv.reader(source), [])
            if existing_header != PRICE_HISTORY_COLUMNS:
                self.path.unlink()
                progress(
                    "Пересоздаю историю цен: схема колонок была устаревшей"
                )
        new_file = not self.path.exists() or self.path.stat().st_size == 0
        self.file = self.path.open("a", newline="", encoding="utf-8-sig")
        self.writer = csv.DictWriter(
            self.file,
            fieldnames=PRICE_HISTORY_COLUMNS,
            extrasaction="ignore",
        )
        if new_file:
            self.writer.writeheader()
        self.rows_written = 0

    def write(self, product: Product) -> None:
        prices = [offer.price for offer in product.offers if offer.price is not None]
        if not prices:
            return
        quantities = [
            offer.quantity_in_stock
            for offer in product.offers
            if offer.quantity_in_stock is not None
        ]
        self.writer.writerow(
            {
                "parsed_at": product.parsed_at,
                "price_date": product.parsed_at[:10],
                "source": product.source,
                "product_id": product.source_product_id,
                "price": min(prices),
                "quantity_available": sum(quantities) if quantities else "",
            }
        )
        self.rows_written += 1

    def __enter__(self) -> "PriceHistoryWriter":
        return self

    def __exit__(self, *_: object) -> None:
        self.file.close()


class State:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                source TEXT NOT NULL,
                source_product_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (source, source_product_id)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS done_items (
                source TEXT NOT NULL,
                item_key TEXT NOT NULL,
                PRIMARY KEY (source, item_key)
            )
            """
        )
        self.connection.commit()
        self.stats = {"new": 0, "changed": 0, "unchanged": 0}

    def done_items(self, source: str) -> set[str]:
        rows = self.connection.execute(
            "SELECT item_key FROM done_items WHERE source=?",
            (source,),
        ).fetchall()
        return {str(row[0]) for row in rows}

    def mark_item_done(self, source: str, item_key: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO done_items VALUES (?, ?)",
            (source, item_key),
        )

    def clear_items(self, source: str) -> None:
        self.connection.execute(
            "DELETE FROM done_items WHERE source=?",
            (source,),
        )
        self.connection.commit()

    def record(self, product: Product) -> str:
        row = self.connection.execute(
            "SELECT fingerprint FROM products "
            "WHERE source=? AND source_product_id=?",
            (product.source, product.source_product_id),
        ).fetchone()
        fingerprint = product.fingerprint()
        if row is None:
            status = "new"
            self.connection.execute(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?)",
                (
                    product.source,
                    product.source_product_id,
                    fingerprint,
                    product.parsed_at,
                    product.parsed_at,
                ),
            )
        else:
            status = "unchanged" if row[0] == fingerprint else "changed"
            self.connection.execute(
                "UPDATE products SET fingerprint=?, last_seen=? "
                "WHERE source=? AND source_product_id=?",
                (
                    fingerprint,
                    product.parsed_at,
                    product.source,
                    product.source_product_id,
                ),
            )
        self.stats[status] += 1
        return status

    def commit(self) -> None:
        self.connection.commit()

    def __enter__(self) -> "State":
        return self

    def __exit__(self, *_: object) -> None:
        self.connection.commit()
        self.connection.close()


def run_carcity_parser(
    *,
    output_dir: str | Path | None = None,
    categories: str | Iterable[str] = "all",
    limit: int | None = None,
    per_group: int | None = None,
    limit_tires: int | None = None,
    limit_oils: int | None = None,
    limit_filters: int | None = None,
    limit_batteries: int | None = None,
    workers: int = DEFAULT_WORKERS,
    min_delay: float = DEFAULT_MIN_DELAY,
    per_page: int = DEFAULT_PER_PAGE,
    max_pages: int = MAX_PAGES,
    resume: bool = False,
    state_path: str | Path | None = None,
    respect_robots: bool = True,
) -> dict[str, object]:
    """Запустить Carcity и вернуть JSON-совместимую сводку.

    Это основной публичный API для Airflow PythonOperator. Все параметры
    состоят из простых типов и могут передаваться через ``op_kwargs``.
    """
    if workers < 1:
        raise ValueError("workers должен быть не меньше 1")
    if limit is not None and limit <= 0:
        limit = None
    if per_group is not None and per_group <= 0:
        per_group = None
    raw_group_limits = {
        "tires": limit_tires,
        "oils": limit_oils,
        "filters": limit_filters,
        "batteries": limit_batteries,
    }
    group_limits = {
        group: (None if value is not None and value <= 0 else value)
        for group, value in raw_group_limits.items()
        if value is not None
    }

    started_at = time.monotonic()
    default_output = Path(__file__).resolve().parents[1] / "data" / SOURCE
    output_path = Path(output_dir) if output_dir else default_output
    output_path.mkdir(parents=True, exist_ok=True)
    history_path = output_path / "carcity_price_history.csv"
    database_path = Path(state_path) if state_path else output_path / "state.sqlite"
    if not resume:
        for legacy_name in (
            "carcity_products.csv",
            "carcity_quality_gaps.csv",
            "carcity_uncategorized.csv",
        ):
            legacy_path = output_path / legacy_name
            if legacy_path.exists():
                legacy_path.unlink()
                progress(f"Удалён старый смешанный файл: {legacy_path}")

    fetcher = Fetcher(
        min_delay=min_delay,
        respect_robots=respect_robots,
    )
    scraper = CarCityScraper(
        fetcher,
        per_page=per_page,
        max_pages=max_pages,
    )
    selected_groups = parse_groups(categories)
    log.info("Обнаружение товаров: %s", ", ".join(sorted(selected_groups)))
    limits_text = ", ".join(
        f"{group}: {group_limits.get(group, per_group) or 'без лимита'}"
        for group in sorted(selected_groups)
    )
    progress(
        "Старт: "
        f"категории={','.join(sorted(selected_groups))}, "
        f"limit={limit or 'без лимита'}, "
        f"per_group={per_group or 'без лимита'}, "
        f"лимиты таблиц={{{limits_text}}}, "
        f"workers={workers}, "
        f"per_page={per_page}, max_pages={max_pages}, "
        f"robots={'да' if respect_robots else 'нет'}"
    )
    progress(f"Папка результатов: {output_path.resolve()}")
    items = scraper.discover(
        selected_groups,
        limit=limit,
        per_group=per_group,
        group_limits=group_limits,
    )
    discovered = len(items)

    product_count = 0
    processed = 0
    skipped = 0
    errors = 0

    with State(database_path) as state:
        if resume:
            done = state.done_items(SOURCE)
            before = len(items)
            items = [item for item in items if item[0] not in done]
            skipped = before - len(items)
            progress(
                f"Resume: пропущено уже обработанных={skipped}, "
                f"осталось={len(items)}"
            )
        else:
            state.clear_items(SOURCE)

        if not items:
            progress(
                "Нет URL для разбора карточек. Смотрите сообщения листинга выше: "
                "HTTP, final_url, title и число упоминаний /product/."
            )
        else:
            progress(f"Начинаю разбор {len(items)} карточек в {workers} потоков")

        with (
            CategoryCsvWriter(
                output_path,
                selected_groups,
                append=resume,
            ) as csv_writer,
            PriceHistoryWriter(history_path) as history_writer,
            ThreadPoolExecutor(max_workers=workers) as pool,
        ):
            futures = {
                pool.submit(scraper.parse, *item): item
                for item in items
            }
            for completed, future in enumerate(as_completed(futures), 1):
                item = futures[future]
                try:
                    product = future.result()
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    log.warning("Ошибка разбора %s: %s", item[0], exc)
                    progress(
                        f"ОШИБКА карточки [{completed}/{len(items)}] "
                        f"{item[0]}: {type(exc).__name__}: {exc}"
                    )
                    continue
                processed += 1
                if product is not None:
                    csv_writer.write(product)
                    status = state.record(product)
                    if status in ("new", "changed"):
                        history_writer.write(product)
                    product_count += 1
                else:
                    progress(
                        f"Карточка пропущена [{completed}/{len(items)}]: {item[0]}"
                    )
                state.mark_item_done(SOURCE, item[0])
                if completed <= 10 or completed % 50 == 0 or completed == len(items):
                    progress(
                        f"Карточки: {completed}/{len(items)}, "
                        f"товаров={product_count}, строк CSV={csv_writer.rows_written}, "
                        f"ошибок={errors}"
                    )
                if completed % 200 == 0:
                    state.commit()
                    log.info(
                        "Обработано %d/%d, товаров %d, ошибок %d",
                        completed,
                        len(items),
                        product_count,
                        errors,
                    )

            summary = RunSummary(
                discovered=discovered,
                processed=processed,
                products=product_count,
                rows_written=csv_writer.rows_written,
                rows_by_group=dict(csv_writer.rows_by_group),
                history_rows_written=history_writer.rows_written,
                skipped=skipped,
                errors=errors,
                output_files=csv_writer.output_files(),
                history_csv=str(history_path.resolve()),
                state_db=str(database_path.resolve()),
                elapsed_seconds=round(time.monotonic() - started_at, 2),
                new=state.stats["new"],
                changed=state.stats["changed"],
                unchanged=state.stats["unchanged"],
            )

    result = summary.as_dict()
    log.info("Carcity завершён: %s", json.dumps(result, ensure_ascii=False))
    progress(
        f"Готово: найдено={discovered}, обработано={processed}, "
        f"товаров={product_count}, ошибок={errors}, "
        f"время={result['elapsed_seconds']} с"
    )
    return result


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Автономный парсер carcity.kz",
    )
    parser.add_argument(
        "--categories",
        default="all",
        help="all или список: tires,oils,filters,batteries",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Папка результатов. По умолчанию data/carcity.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Общий лимит товаров для теста. 0 означает без лимита.",
    )
    parser.add_argument(
        "--per-group",
        type=int,
        default=0,
        help="Лимит товаров на каждую выбранную группу. 0 означает без лимита.",
    )
    parser.add_argument(
        "--limit-tires",
        type=int,
        default=None,
        help="Лимит строк в carcity_tires.csv. Имеет приоритет над --per-group.",
    )
    parser.add_argument(
        "--limit-oils",
        type=int,
        default=None,
        help="Лимит строк в carcity_oils.csv. Имеет приоритет над --per-group.",
    )
    parser.add_argument(
        "--limit-filters",
        type=int,
        default=None,
        help="Лимит строк в carcity_filters.csv. Имеет приоритет над --per-group.",
    )
    parser.add_argument(
        "--limit-batteries",
        type=int,
        default=None,
        help="Лимит строк в carcity_batteries.csv. Имеет приоритет над --per-group.",
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--min-delay", type=float, default=DEFAULT_MIN_DELAY)
    parser.add_argument("--per-page", type=int, default=DEFAULT_PER_PAGE)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--state", default="", help="Путь к state.sqlite.")
    parser.add_argument(
        "--no-robots",
        action="store_true",
        help="Не проверять robots.txt.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        summary = run_carcity_parser(
            output_dir=args.output_dir or None,
            categories=args.categories,
            limit=args.limit or None,
            per_group=args.per_group or None,
            limit_tires=args.limit_tires,
            limit_oils=args.limit_oils,
            limit_filters=args.limit_filters,
            limit_batteries=args.limit_batteries,
            workers=args.workers,
            min_delay=args.min_delay,
            per_page=args.per_page,
            max_pages=args.max_pages,
            resume=args.resume,
            state_path=args.state or None,
            respect_robots=not args.no_robots,
        )
    except (ValueError, requests.RequestException) as exc:
        log.error("%s", exc)
        return 1

    print("\n=== carcity ===")
    print(f"Найдено товаров : {summary['discovered']}")
    print(f"Обработано       : {summary['processed']}")
    print(f"Товаров записано: {summary['products']}")
    print(f"Строк в CSV      : {summary['rows_written']}")
    print(
        "По таблицам       : "
        + ", ".join(
            f"{group}={count}"
            for group, count in summary["rows_by_group"].items()
        )
    )
    print(f"Ошибок           : {summary['errors']}")
    for group, path in summary["output_files"].items():
        print(f"CSV {group:<10}: {path}")
    print(f"История цен      : {summary['history_csv']}")
    print(f"Время            : {summary['elapsed_seconds']} с")
    return 0 if summary["products"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
