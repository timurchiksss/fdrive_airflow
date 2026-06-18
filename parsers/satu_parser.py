#!/usr/bin/env python3
"""
Parse Satu.kz auto products from four target categories.

The parser uses direct HTTP requests, reads the server-rendered Apollo cache,
and writes a separate CSV for tires, oils, filters, and batteries.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any, Iterable

import requests


SOURCE = "satu_kz"
WEB_HOST = "https://satu.kz"

CORE_AUTO_CATEGORY_RULES = {
    "motor_oils": {
        "name": "Моторные масла",
        "alias": "Motornye-masla",
        "category_ids": {341022},
        "attributes": [
            "brand",
            "product_line",
            "viscosity",
            "volume_liters",
            "oil_type",
            "engine_type",
            "specification",
            "package_type",
            "acea_class",
            "approvals",
        ],
    },
    "batteries": {
        "name": "Аккумуляторы",
        "alias": "Avtomobilnye-akkumulyatory",
        "category_ids": {120201},
        "attributes": [
            "brand",
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
    },
    "tires": {
        "name": "Шины",
        "alias": "Shiny",
        "category_ids": {801229, 801230, 801225, 801226, 801227, 801228},
        "attributes": [
            "brand",
            "width",
            "profile",
            "diameter",
            "season",
            "load_index",
            "speed_index",
            "runflat",
            "model_name",
            "weight",
        ],
    },
    "filters": {
        "name": "Фильтры",
        "alias": "Avtomobilnye-filtry",
        "category_ids": {12021001, 12021002, 12021003, 12021004, 12021005},
        "attributes": [
            "brand",
            "filter_type",
            "compatible_brand",
            "compatible_model",
            "oem_number",
            "additional_information",
        ],
    },
}

CATEGORY_ID_TO_KEY = {
    category_id: key
    for key, rule in CORE_AUTO_CATEGORY_RULES.items()
    for category_id in rule["category_ids"]
}

GROUP_OUTPUT_COLUMNS = {
    "tires": [
        "product_id", "name", "price", "url", "slug", "images", "brand",
        "season", "size", "width", "height", "diameter",
        "weight_single_index", "weight_double_index", "velocity_index",
        "quantity_available", "tyre_auto_type_name", "tyre_stud_type_name",
        "is_ecar", "article_sku", "rating", "reviews_count", "seller_count",
        "city", "parsed_at", "model_name", "weight",
    ],
    "oils": [
        "product_id", "name", "price", "url", "slug", "category",
        "brand_name", "images", "Вид масла", "Класс API",
        "Класс вязкости SAE", "Объем упаковки, л", "Область применения",
        "Тип коробки передач", "Назначение", "Упаковка", "Класс ACEA",
        "Допуски", "Тип двигателя", "article_sku", "rating",
        "reviews_count", "seller_count", "city", "parsed_at",
    ],
    "filters": [
        "product_id", "name", "price", "url", "slug", "category", "brand",
        "images", "quantity_available", "filter_type",
        "manufacturer_article", "compatible_brand", "compatible_model",
        "compatible_years", "oem_numbers", "additional_information",
        "article_sku", "rating", "reviews_count", "seller_count", "city", "parsed_at",
    ],
    "batteries": [
        "product_id", "name", "price", "url", "slug", "category", "brand",
        "images", "quantity_available", "capacity_ah", "voltage_v",
        "start_current_a", "polarity", "battery_type", "dimensions",
        "terminal_type", "case_type", "weight", "features", "length",
        "width", "height", "article_sku", "rating", "reviews_count",
        "seller_count", "city", "parsed_at",
    ],
}

KNOWN_BRANDS = [
    "castrol",
    "mobil",
    "liqui moly",
    "elf",
    "bardahl",
    "s-oil",
    "kixx",
    "mannol",
    "shell",
    "total",
    "motul",
    "gazpromneft",
    "газпромнефть",
    "rosneft",
    "роснефть",
    "toyota",
    "varta",
    "mutlu",
    "akom",
    "tyumen",
    "bosch",
    "hankook",
    "bridgestone",
    "michelin",
    "goodyear",
    "pirelli",
    "continental",
    "yokohama",
    "kumho",
    "nexen",
    "triangle",
    "sakura",
    "mann-filter",
    "mahle",
    "filtron",
]

ATTRIBUTE_ALIASES = {
    "производитель": "brand",
    "бренд": "brand",
    "brand": "brand",
    "вид масла": "oil_type",
    "вязкость масла по sae": "viscosity",
    "вязкость": "viscosity",
    "объем": "volume_liters",
    "объём": "volume_liters",
    "объем, л": "volume_liters",
    "объём, л": "volume_liters",
    "для типа двигателей": "engine_type",
    "тип двигателя": "engine_type",
    "стандарт api": "specification",
    "стандарт acea": "acea_class",
    "класс acea": "acea_class",
    "допуск": "approvals",
    "допуски": "approvals",
    "тип упаковки": "package_type",
    "упаковка": "package_type",
    "емкость аккумулятора": "capacity_ah",
    "емкость": "capacity_ah",
    "ёмкость": "capacity_ah",
    "напряжение аккумулятора": "voltage_v",
    "напряжение": "voltage_v",
    "пусковой ток": "start_current_a",
    "стартовый ток": "start_current_a",
    "полярность": "polarity",
    "тип аккумулятора": "battery_type",
    "размеры": "dimensions",
    "габаритные размеры": "dimensions",
    "тип клемм": "terminal_type",
    "ширина профиля": "width",
    "ширина": "width",
    "высота профиля": "profile",
    "профиль": "profile",
    "посадочный диаметр": "diameter",
    "посадочный диаметр шины": "diameter",
    "диаметр": "diameter",
    "сезонность шин": "season",
    "сезон": "season",
    "индекс нагрузки": "load_index",
    "индекс нагрузки шины": "load_index",
    "индекс скорости": "speed_index",
    "runflat": "runflat",
    "run flat": "runflat",
    "тип фильтра": "filter_type",
    "тип автомобильного фильтра": "filter_type",
    "oem номер": "oem_number",
    "oem-номер": "oem_number",
    "oe номер": "oem_number",
    "артикул производителя": "oem_number",
    "номер детали": "oem_number",
    "марка автомобиля": "compatible_brand",
    "совместимая марка": "compatible_brand",
    "модель автомобиля": "compatible_model",
    "совместимая модель": "compatible_model",
    "вес": "weight",
    "вес, кг": "weight",
    "особенности": "features",
    "длина": "length",
    "высота": "height",
    "модель": "model_name",
    "дополнительная информация": "additional_information",
}

RE_AD_WORDS = re.compile(
    r"\b(купить|акция|скидка|рассрочка|оригинал|новинка|доставка|sale|new)\b",
    re.IGNORECASE,
)
RE_SPACES = re.compile(r"\s+")
RE_VOLUME = re.compile(r"(?P<value>\d+(?:[.,]\d+)?)\s*(?:л|l|литр(?:а|ов)?)\b", re.IGNORECASE)
RE_VISCOSITY = re.compile(r"\b(?P<value>\d{1,2}w[-\s]?\d{2})\b", re.IGNORECASE)
RE_TIRE = re.compile(r"\b(?P<width>\d{3})[/xх](?P<profile>\d{2})\s*r(?P<diameter>\d{2})\b", re.IGNORECASE)
RE_TIRE_SPLIT_R = re.compile(
    r"\b(?P<width>\d{3})/(?P<profile>\d{2}),?\s*r(?P<diameter>\d{2}(?:[.,]\d)?)\b",
    re.IGNORECASE,
)
RE_TIRE_DECIMAL_R = re.compile(r"\b(?P<width>\d{1,2}(?:[.,]\d{1,2})?)\s*r(?P<diameter>\d{2})\b", re.IGNORECASE)
RE_TIRE_DASH = re.compile(r"\b(?P<width>\d{1,2}(?:[.,]\d{1,2})?)-(?P<diameter>\d{2})\b", re.IGNORECASE)
RE_TIRE_ALT = re.compile(r"\b(?P<diameter>\d{2,3})[xх](?P<width>\d{1,3}(?:[.,]\d)?)\s*r?(?P<rim>\d{1,2})\b", re.IGNORECASE)
RE_BATTERY_CAPACITY = re.compile(r"\b(?P<value>\d{2,3})\s*(?:ah|а/ч|ач|а\.ч\.?)\b", re.IGNORECASE)
RE_VOLTAGE = re.compile(r"\b(?P<value>6|12|24)\s*(?:v|в)\b", re.IGNORECASE)
RE_START_CURRENT = re.compile(r"\b(?P<value>\d{3,4})\s*(?:a|а)\b", re.IGNORECASE)
RE_LOAD_SPEED = re.compile(r"\b(?P<load>\d{2,3})/?(?:\d{2,3})?(?P<speed>[A-Z]\d?)\b", re.IGNORECASE)
RE_OIL_SPEC = re.compile(r"\b(?P<value>(?:A\d/B\d|C\d|E\d+|SP|SN|SM|SL|CF|CK-4|GF-\d)(?:[/\s-]*(?:A\d/B\d|C\d|E\d+|SP|SN|SM|SL|CF|CK-4|GF-\d))*)\b", re.IGNORECASE)
RE_PRODUCT_URL = re.compile(r"/p(?P<id>\d+)-(?P<slug>[^\"'<> ]+?)\.html")
RE_OEM_CODE = re.compile(r"\b(?=[A-ZА-Я0-9-]*\d)(?=[A-ZА-Я0-9-]*[A-ZА-Я])[A-ZА-Я0-9][A-ZА-Я0-9./-]{4,}\b", re.IGNORECASE)

FILTER_COMPAT_BRANDS = [
    "камаз",
    "газ",
    "газель",
    "паз",
    "маз",
    "урал",
    "белаз",
    "краз",
    "case",
    "liebherr",
    "volvo",
    "cummins",
    "toyota",
    "hyundai",
    "kia",
    "nissan",
    "renault",
    "volkswagen",
    "audi",
    "bmw",
    "mercedes",
]


@dataclass
class State:
    flat_products: list[dict[str, Any]] = field(default_factory=list)
    seen_source_products: set[str] = field(default_factory=set)


class SatuParseError(RuntimeError):
    pass


class SatuHttpClient:
    def __init__(self, *, timeout: float = 60):
        self.timeout = timeout
        self._local = threading.local()
        self._sessions: list[requests.Session] = []
        self._sessions_lock = threading.Lock()

    def __enter__(self) -> "SatuHttpClient":
        self._session()
        return self

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is not None:
            return session
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            }
        )
        self._local.session = session
        with self._sessions_lock:
            self._sessions.append(session)
        return session

    def __exit__(self, exc_type, exc, tb) -> None:
        for session in self._sessions:
            session.close()

    def fetch_text(self, url: str) -> str:
        try:
            response = self._session().get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SatuParseError(f"GET {url} failed: {exc}") from exc
        return response.text


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = RE_SPACES.sub(" ", text)
    return text.strip()


def normalize_attr_name(title: str) -> str:
    key = clean_text(title).lower().replace("ё", "е")
    if key.startswith(("допуск ", "допуски ")):
        return "approvals"
    key = ATTRIBUTE_ALIASES.get(key, key)
    key = re.sub(r"[^0-9a-zа-я_]+", "_", key, flags=re.IGNORECASE)
    return key.strip("_").lower() or "unknown_attribute"


def normalize_numeric_text(value: str) -> str:
    match = re.search(r"\d+(?:[.,]\d+)?", value)
    return match.group(0).replace(",", ".") if match else value


def normalize_brand(raw_name: str, explicit: str = "") -> str:
    if explicit:
        return clean_text(explicit).title()
    lowered = raw_name.lower()
    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(brand)}(?!\w)", lowered):
            return brand.title()
    tokens = clean_text(raw_name).split()
    skip = {
        "автомобильный",
        "автомобильная",
        "автомобильное",
        "автомобильные",
        "для",
        "моторное",
        "масло",
        "шина",
        "шины",
        "аккумулятор",
        "фильтр",
    }
    for token in tokens:
        if token.lower() not in skip and re.search(r"[A-Za-zА-Яа-я]", token):
            return token.strip(" ,.;:").title()
    return ""


def infer_product_line(name: str, brand: str) -> str:
    text = clean_text(name)
    if brand:
        text = re.sub(rf"(?i)\b{re.escape(brand)}\b", " ", text)
    text = re.sub(r"(?i)\b(моторное|масло|синтетическое|полусинтетическое|минеральное)\b", " ", text)
    text = RE_VISCOSITY.sub(" ", text)
    text = RE_VOLUME.sub(" ", text)
    return RE_SPACES.sub(" ", text).strip(" ,.;:-")


def infer_filter_type(name: str) -> str:
    lowered = name.lower()
    options = {
        "масля": "oil",
        "воздуш": "air",
        "салон": "cabin",
        "топлив": "fuel",
        "акпп": "transmission",
    }
    for marker, value in options.items():
        if marker in lowered:
            return value
    return ""


def infer_battery_type(text: str) -> str:
    lowered = text.lower()
    for marker, value in {
        "agm": "AGM",
        "efb": "EFB",
        "gel": "GEL",
        "гелев": "GEL",
        "ca/ca": "Ca/Ca",
        "свинц": "lead_acid",
    }.items():
        if marker in lowered:
            return value
    return ""


def infer_filter_compatibility(name: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    lowered = name.lower()
    brands = []
    for brand in FILTER_COMPAT_BRANDS:
        if re.search(rf"(?<!\w){re.escape(brand)}(?!\w)", lowered):
            brands.append(brand.upper() if brand in {"газ", "маз", "паз", "урал", "камаз"} else brand.title())
    if brands:
        attrs["compatible_brand"] = "; ".join(dict.fromkeys(brands))

    models = re.findall(r"\b(?:двс\s*)?[A-ZА-Я]{1,6}[- ]?\d{2,5}(?:[.-]\d+)?\b", name, flags=re.IGNORECASE)
    if models:
        attrs["compatible_model"] = "; ".join(dict.fromkeys(clean_text(model).upper() for model in models[:8]))

    oem_candidates = []
    for candidate in RE_OEM_CODE.findall(name):
        candidate = candidate.strip(" /,.;:")
        lowered_candidate = candidate.lower()
        if lowered_candidate in {"cummins", "triangle", "starmaxx"} or lowered_candidate.startswith(("евро", "euro")):
            continue
        if len(candidate) >= 5:
            oem_candidates.append(candidate.upper())
    if oem_candidates:
        attrs["oem_number"] = "; ".join(dict.fromkeys(oem_candidates[:8]))
    return attrs


def normalize_product_name(name: str, attrs: dict[str, str]) -> str:
    text = clean_text(name).replace("ё", "е").replace("Ё", "Е")
    text = RE_AD_WORDS.sub(" ", text)
    text = re.sub(r"[™®©]", "", text)
    text = re.sub(r"\s*,\s*", " ", text)
    text = RE_SPACES.sub(" ", text).strip()
    viscosity = attrs.get("viscosity")
    if viscosity:
        normalized = viscosity.upper().replace(" ", "").replace("W", "W-").replace("W--", "W-")
        text = RE_VISCOSITY.sub(normalized, text)
    volume = attrs.get("volume_liters")
    if volume:
        text = RE_VOLUME.sub(f"{volume} л", text)
    return text


def extract_derived_attrs(name: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    volume = RE_VOLUME.search(name)
    if volume:
        attrs["volume_liters"] = volume.group("value").replace(",", ".")
    viscosity = RE_VISCOSITY.search(name)
    if viscosity:
        attrs["viscosity"] = viscosity.group("value").upper().replace(" ", "").replace("W", "W-").replace("W--", "W-")
    tire = RE_TIRE_SPLIT_R.search(name) or RE_TIRE.search(name)
    if tire:
        attrs["width"] = tire.group("width")
        attrs["profile"] = tire.group("profile")
        attrs["diameter"] = f"R{tire.group('diameter').replace(',', '.')}"
    else:
        tire_alt = RE_TIRE_ALT.search(name)
        if tire_alt:
            attrs["width"] = tire_alt.group("width").replace(",", ".")
            attrs["diameter"] = f"R{tire_alt.group('rim')}"
        else:
            tire_decimal = RE_TIRE_DECIMAL_R.search(name) or RE_TIRE_DASH.search(name)
            if tire_decimal:
                attrs["width"] = tire_decimal.group("width").replace(",", ".")
                attrs["diameter"] = f"R{tire_decimal.group('diameter').replace(',', '.')}"
    battery_capacity = RE_BATTERY_CAPACITY.search(name)
    if battery_capacity:
        attrs["capacity_ah"] = battery_capacity.group("value")
    voltage = RE_VOLTAGE.search(name)
    if voltage:
        attrs["voltage_v"] = voltage.group("value")
    start_current = RE_START_CURRENT.search(name)
    if start_current:
        attrs["start_current_a"] = start_current.group("value")
    load_speed = RE_LOAD_SPEED.search(name)
    if load_speed and ("width" in attrs or "diameter" in attrs):
        attrs["load_index"] = load_speed.group("load")
        attrs["speed_index"] = load_speed.group("speed").upper()
    lowered = name.lower()
    if "runflat" in lowered or "run flat" in lowered:
        attrs["runflat"] = "true"
    for season, markers in {
        "winter": ["зим", "winter"],
        "summer": ["лет", "summer"],
        "all_season": ["всесез", "all season", "all-season"],
    }.items():
        if any(marker in lowered for marker in markers):
            attrs["season"] = season
            break
    if "синтет" in lowered:
        attrs["oil_type"] = "synthetic"
    elif "полусинтет" in lowered:
        attrs["oil_type"] = "semi_synthetic"
    elif "минерал" in lowered:
        attrs["oil_type"] = "mineral"
    if "дизель" in lowered and "бензин" in lowered:
        attrs["engine_type"] = "gasoline; diesel"
    elif "дизель" in lowered:
        attrs["engine_type"] = "diesel"
    elif "бензин" in lowered:
        attrs["engine_type"] = "gasoline"
    if any(marker in lowered for marker in ["канистр", "бутыл", "флакон"]):
        attrs["package_type"] = "bottle"
    filter_type = infer_filter_type(name)
    if filter_type:
        attrs["filter_type"] = filter_type
    oil_spec = RE_OIL_SPEC.search(name)
    if oil_spec:
        attrs["specification"] = oil_spec.group("value").upper().strip(" -/")
    if "прямая" in lowered:
        attrs["polarity"] = "прямая"
    elif "обратная" in lowered:
        attrs["polarity"] = "обратная"
    if re.search(r"\b6\s*[сc]т\b", lowered):
        attrs["voltage_v"] = "12"
    return attrs


def extract_apollo_state(page_html: str) -> dict[str, Any]:
    marker = "window.ApolloCacheState"
    marker_pos = page_html.find(marker)
    if marker_pos < 0:
        raise SatuParseError("Apollo cache not found in page HTML")
    start = page_html.find("{", marker_pos)
    if start < 0:
        raise SatuParseError("Apollo cache JSON start not found")

    level = 0
    in_string = False
    escaped = False
    for index, char in enumerate(page_html[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "{":
                level += 1
            elif char == "}":
                level -= 1
                if level == 0:
                    return json.loads(page_html[start : index + 1])
    raise SatuParseError("Apollo cache JSON end not found")


def deref_value(value: Any, cache: dict[str, Any]) -> Any:
    if isinstance(value, dict) and "__ref" in value:
        return cache.get(value["__ref"], value)
    return value


def attribute_values(attr: dict[str, Any], cache: dict[str, Any]) -> str:
    values = []
    for raw_value in attr.get("values") or []:
        value = deref_value(raw_value, cache)
        if isinstance(value, dict):
            values.append(clean_text(value.get("value") or value.get("name") or value.get("title")))
        else:
            values.append(clean_text(value))
    return "; ".join(v for v in values if v)


def find_listing_page(cache: dict[str, Any]) -> dict[str, Any]:
    for key, value in (cache.get("_FAST_CACHE") or {}).items():
        if "ListingQuery" not in key:
            continue
        page = (((value or {}).get("result") or {}).get("listing") or {}).get("page")
        if isinstance(page, dict):
            return page
    raise SatuParseError("Listing page not found in Apollo cache")


def find_product_detail(cache: dict[str, Any], product_id: str) -> dict[str, Any]:
    exact = f'product({{"id":{product_id}}})'
    root = cache.get("ROOT_QUERY") or {}
    if exact in root:
        return root[exact]
    for key, value in root.items():
        if key.startswith("product(") and str(product_id) in key and isinstance(value, dict):
            return value
    for key, value in (cache.get("_FAST_CACHE") or {}).items():
        if "ProductCardPageQuery" not in key:
            continue
        product = ((value or {}).get("result") or {}).get("product")
        if isinstance(product, dict) and str(product.get("id")) == str(product_id):
            return product
    raise SatuParseError(f"Product {product_id} not found in detail Apollo cache")


def product_url(product: dict[str, Any]) -> str:
    product_id = product.get("id")
    url_text = product.get("urlText") or ""
    if product_id and url_text:
        return f"{WEB_HOST}/p{product_id}-{url_text}.html"
    if product_id:
        return f"{WEB_HOST}/p{product_id}.html"
    return ""


def collect_images(product: dict[str, Any]) -> str:
    urls: list[str] = []
    for key, value in product.items():
        if key.startswith("image") and isinstance(value, str) and value.startswith("http"):
            urls.append(value)
        if key.startswith("images") and isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.startswith("http"):
                    urls.append(item)
                elif isinstance(item, dict):
                    url = item.get("url") or item.get("src")
                    if isinstance(url, str) and url.startswith("http"):
                        urls.append(url)
    seen: set[str] = set()
    unique = [url for url in urls if not (url in seen or seen.add(url))]
    return json.dumps(unique, ensure_ascii=False)


def category_key_for_product(product: dict[str, Any], fallback_key: str) -> str | None:
    category_id = product.get("categoryId")
    if isinstance(category_id, int) and category_id in CATEGORY_ID_TO_KEY:
        return CATEGORY_ID_TO_KEY[category_id]
    category = product.get("category")
    path = category.get("path") if isinstance(category, dict) else None
    if isinstance(path, list):
        for item in reversed(path):
            item_id = item.get("id") if isinstance(item, dict) else None
            if item_id in CATEGORY_ID_TO_KEY:
                return CATEGORY_ID_TO_KEY[item_id]
    return fallback_key


def merge_attr(attrs: dict[str, str], key: str, value: str) -> None:
    value = clean_text(value)
    if not value:
        return
    if key in {"volume_liters", "capacity_ah", "voltage_v", "start_current_a"}:
        value = normalize_numeric_text(value)
    if key in attrs and attrs[key]:
        if value not in attrs[key].split("; "):
            attrs[key] = f"{attrs[key]}; {value}"
    else:
        attrs[key] = value


def build_flat_product(
    listing_product: dict[str, Any],
    detail_product: dict[str, Any] | None,
    detail_cache: dict[str, Any] | None,
    category_key: str,
    parsed_at: str,
) -> dict[str, Any]:
    product = detail_product or listing_product
    cache = detail_cache or {}
    name = clean_text(product.get("name") or product.get("nameForCatalog") or listing_product.get("name"))
    if not name:
        name = clean_text(listing_product.get("name"))
    description = clean_text(product.get("descriptionPlain") or product.get("descriptionFull"))[:2000]

    attrs = extract_derived_attrs(f"{name} {description}")
    dimension_parts: dict[str, str] = {}
    for attr in product.get("attributes") or []:
        raw_attr_name = clean_text(attr.get("name", ""))
        attr_name = normalize_attr_name(raw_attr_name)
        value = attribute_values(attr, cache)
        if category_key == "batteries":
            raw_key = raw_attr_name.lower().replace("ё", "е")
            if raw_key in {"длина", "ширина", "высота"}:
                dimension_parts[raw_key] = normalize_numeric_text(value)
                merge_attr(attrs, {"длина": "length", "ширина": "width", "высота": "height"}[raw_key], value)
        if attr_name == "specification":
            merge_attr(attrs, attr_name, value)
        elif attr_name in flat_attribute_names():
            merge_attr(attrs, attr_name, value)

    manufacturer = product.get("manufacturerInfo") or listing_product.get("manufacturerInfo") or {}
    brand = normalize_brand(name, attrs.get("brand") or manufacturer.get("name", ""))
    if brand:
        attrs["brand"] = brand
    if category_key == "motor_oils" and not attrs.get("product_line"):
        attrs["product_line"] = infer_product_line(name, brand)
    if category_key == "filters" and not attrs.get("filter_type"):
        attrs["filter_type"] = infer_filter_type(name)
    if category_key == "filters":
        for key, value in infer_filter_compatibility(name).items():
            merge_attr(attrs, key, value)
    if category_key == "batteries":
        dimensions_match = re.search(
            r"\b(?P<length>\d{2,3})\s*[xх×]\s*(?P<width>\d{2,3})\s*[xх×]\s*(?P<height>\d{2,3})\b",
            f"{name} {description}",
            flags=re.IGNORECASE,
        )
        if dimensions_match:
            for key in ("length", "width", "height"):
                attrs.setdefault(key, dimensions_match.group(key))
            attrs.setdefault(
                "dimensions",
                "x".join(dimensions_match.group(key) for key in ("length", "width", "height")),
            )
        if dimension_parts and not attrs.get("dimensions"):
            length = dimension_parts.get("длина", "")
            width = dimension_parts.get("ширина", "")
            height = dimension_parts.get("высота", "")
            dims = "x".join(part for part in [length, width, height] if part)
            if dims:
                attrs["dimensions"] = f"{dims} мм"
        if not attrs.get("battery_type"):
            battery_type = infer_battery_type(name + " " + " ".join(attrs.values()))
            if battery_type:
                attrs["battery_type"] = battery_type
    if category_key == "motor_oils" and attrs.get("volume_liters") and not attrs.get("package_type"):
        attrs["package_type"] = "bottle"
    if category_key == "tires" and not attrs.get("model_name"):
        model = product.get("model") or listing_product.get("model")
        if isinstance(model, dict):
            model = model.get("name") or model.get("title")
        if model:
            attrs["model_name"] = clean_text(model)
    if category_key == "filters" and description and not attrs.get("additional_information"):
        attrs["additional_information"] = description
    if category_key == "batteries" and description and not attrs.get("features"):
        attrs["features"] = description

    allowed = set(CORE_AUTO_CATEGORY_RULES[category_key]["attributes"])
    attrs = {key: value for key, value in attrs.items() if key in allowed}

    category = product.get("category") if isinstance(product.get("category"), dict) else {}
    category_name = category.get("caption") or CORE_AUTO_CATEGORY_RULES[category_key]["name"]
    category_id = product.get("categoryId") or listing_product.get("categoryId")
    source_product_id = str(product.get("id") or listing_product.get("id") or "")
    source_url = product_url(product) or product_url(listing_product)
    if not source_product_id:
        match = RE_PRODUCT_URL.search(source_url)
        source_product_id = match.group("id") if match else source_url
    opinion_counters = product.get("productOpinionCounters") or listing_product.get("productOpinionCounters") or {}
    company = product.get("company") or listing_product.get("company") or {}
    article_sku = product.get("sku") or listing_product.get("sku") or source_product_id

    row = {
        "sku_id": f"{SOURCE}:{source_product_id}",
        "source": SOURCE,
        "source_product_id": source_product_id,
        "source_uid": source_product_id,
        "source_url": source_url,
        "slug": product.get("urlText") or listing_product.get("urlText") or "",
        "category_id": category_id,
        "category": category_name,
        "product_name": name,
        "normalized_name": normalize_product_name(name, attrs),
        "description": description,
        "price": product.get("price") or listing_product.get("price") or "",
        "old_price": product.get("priceOriginal") or listing_product.get("priceOriginal") or "",
        "currency": product.get("priceCurrency") or listing_product.get("priceCurrency") or "KZT",
        "availability": ((product.get("catalogPresence") or {}).get("title") if isinstance(product.get("catalogPresence"), dict) else "")
        or ((product.get("presence") or {}).get("presence") if isinstance(product.get("presence"), dict) else ""),
        "city": ((product.get("company") or {}).get("regionName") if isinstance(product.get("company"), dict) else "")
        or ((listing_product.get("company") or {}).get("regionName") if isinstance(listing_product.get("company"), dict) else ""),
        "parsed_at": parsed_at,
        "image_urls": collect_images(product) or collect_images(listing_product),
        "article_sku": article_sku,
        "rating": opinion_counters.get("rating") if opinion_counters.get("rating") is not None else "",
        "reviews_count": opinion_counters.get("count") if opinion_counters.get("count") is not None else "",
        "seller_count": 1 if isinstance(company, dict) and company.get("id") else "",
    }
    row.update(attrs)
    row["_category_key"] = category_key
    return row


def category_url(alias: str, page: int) -> str:
    base = f"{WEB_HOST}/{alias}"
    if page <= 1:
        return base
    return f"{base}?page={page}"


def iter_listing_products(
    client: SatuHttpClient,
    *,
    category_key: str,
    page_size_hint: int,
    max_pages: int,
    sleep_seconds: float,
    retries: int,
    retry_sleep: float,
) -> Iterable[dict[str, Any]]:
    rule = CORE_AUTO_CATEGORY_RULES[category_key]
    for page_number in range(1, max_pages + 1):
        url = category_url(rule["alias"], page_number)
        page_html = ""
        for attempt in range(1, retries + 1):
            try:
                page_html = client.fetch_text(url)
                break
            except (SatuParseError, TimeoutError) as exc:
                if attempt >= retries:
                    raise SatuParseError(f"GET listing {url} failed after {retries} attempts: {exc}") from exc
                time.sleep(retry_sleep * attempt)
        cache = extract_apollo_state(page_html)
        page = find_listing_page(cache)
        products = page.get("products") or []
        print(
            f"[satu] {rule['name']}, страница={page_number}: получено={len(products)}",
            flush=True,
        )
        if not products:
            break
        yielded = 0
        for item in products:
            product = item.get("product") if isinstance(item, dict) else None
            if not isinstance(product, dict):
                continue
            detected_key = category_key_for_product(product, category_key)
            if detected_key != category_key:
                continue
            yielded += 1
            yield product
        if yielded == 0 and len(products) < page_size_hint:
            break
        if len(products) < page_size_hint:
            break
        time.sleep(sleep_seconds)


def enrich_detail(
    client: SatuHttpClient,
    listing_product: dict[str, Any],
    *,
    retries: int,
    retry_sleep: float,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    source_product_id = str(listing_product.get("id") or "")
    url = product_url(listing_product)
    for attempt in range(1, retries + 1):
        try:
            page_html = client.fetch_text(url)
            cache = extract_apollo_state(page_html)
            return find_product_detail(cache, source_product_id), cache, ""
        except (SatuParseError, TimeoutError) as exc:
            if attempt >= retries:
                return None, None, str(exc)
            time.sleep(retry_sleep * attempt)
    return None, None, "unknown detail error"


def flat_attribute_names() -> list[str]:
    attrs: list[str] = []
    for rule in CORE_AUTO_CATEGORY_RULES.values():
        for attr_name in rule["attributes"]:
            if attr_name not in attrs:
                attrs.append(attr_name)
    return attrs


def output_row(row: dict[str, Any], group: str) -> dict[str, Any]:
    images = row.get("image_urls", "")
    try:
        images = " | ".join(json.loads(images)) if images else ""
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    common = {
        "product_id": row.get("source_product_id", ""),
        "name": row.get("product_name", ""),
        "price": row.get("price", ""),
        "url": row.get("source_url", ""),
        "slug": row.get("slug", ""),
        "category": row.get("category", ""),
        "images": images,
        "brand": row.get("brand", ""),
        "brand_name": row.get("brand", ""),
        "quantity_available": "",
        "article_sku": row.get("article_sku", ""),
        "rating": row.get("rating", ""),
        "reviews_count": row.get("reviews_count", ""),
        "seller_count": row.get("seller_count", ""),
        "city": row.get("city", ""),
        "parsed_at": row.get("parsed_at", ""),
        "weight": row.get("weight", ""),
    }
    if group == "tires":
        width = row.get("width", "")
        height = row.get("profile", "")
        diameter = str(row.get("diameter", "")).lstrip("Rr")
        common.update(
            {
                "season": row.get("season", ""),
                "size": f"{width}/{height} R{diameter}" if width and height and diameter else "",
                "width": width,
                "height": height,
                "diameter": diameter,
                "weight_single_index": row.get("load_index", ""),
                "weight_double_index": "",
                "velocity_index": row.get("speed_index", ""),
                "tyre_auto_type_name": "",
                "tyre_stud_type_name": "",
                "is_ecar": "",
                "model_name": row.get("model_name", ""),
            }
        )
    elif group == "oils":
        common.update(
            {
                "Вид масла": row.get("oil_type", ""),
                "Класс API": row.get("specification", ""),
                "Класс вязкости SAE": row.get("viscosity", ""),
                "Объем упаковки, л": row.get("volume_liters", ""),
                "Область применения": row.get("engine_type", ""),
                "Тип коробки передач": "",
                "Назначение": "",
                "Упаковка": row.get("package_type", ""),
                "Класс ACEA": row.get("acea_class", ""),
                "Допуски": row.get("approvals", ""),
                "Тип двигателя": row.get("engine_type", ""),
            }
        )
    elif group == "filters":
        common.update(
            {
                "filter_type": row.get("filter_type", ""),
                "manufacturer_article": "",
                "compatible_brand": row.get("compatible_brand", ""),
                "compatible_model": row.get("compatible_model", ""),
                "compatible_years": "",
                "oem_numbers": row.get("oem_number", ""),
                "additional_information": row.get("additional_information", ""),
            }
        )
    elif group == "batteries":
        common.update(
            {
                "capacity_ah": row.get("capacity_ah", ""),
                "voltage_v": row.get("voltage_v", ""),
                "start_current_a": row.get("start_current_a", ""),
                "polarity": row.get("polarity", ""),
                "battery_type": row.get("battery_type", ""),
                "dimensions": row.get("dimensions", ""),
                "terminal_type": row.get("terminal_type", ""),
                "case_type": "",
                "features": row.get("features", ""),
                "length": row.get("length", ""),
                "width": row.get("width", ""),
                "height": row.get("height", ""),
            }
        )
    return common


def batched(iterable: Iterable[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    iterator = iter(iterable)
    while batch := list(islice(iterator, size)):
        yield batch


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def write_outputs(
    out_dir: Path,
    state: State,
    raw_count: int,
    started_at: str,
    finished_at: str,
    completed: bool,
    error: str,
    detail_errors: int,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    output_counts: dict[str, int] = {}
    for category_key in CORE_AUTO_CATEGORY_RULES:
        output_key = "oils" if category_key == "motor_oils" else category_key
        rows = [row for row in state.flat_products if row.get("_category_key") == category_key]
        output_counts[output_key] = write_csv(
            out_dir / f"satu_{output_key}.csv",
            (output_row(row, output_key) for row in rows),
            GROUP_OUTPUT_COLUMNS[output_key],
        )
    summary = {
        "source": SOURCE,
        "started_at": started_at,
        "finished_at": finished_at,
        "raw_products": raw_count,
        "unique_source_products": len(state.seen_source_products),
        "flat_products": len(state.flat_products),
        "detail_errors": detail_errors,
        "output_counts": output_counts,
        "completed": completed,
        "error": error,
        "categories": {key: rule["name"] for key, rule in CORE_AUTO_CATEGORY_RULES.items()},
    }
    (out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse Satu.kz products from four target auto categories.")
    parser.add_argument(
        "--categories",
        default="motor_oils,batteries,tires,filters",
        help="Comma-separated keys: motor_oils,batteries,tires,filters.",
    )
    parser.add_argument("--max-products", type=int, default=0, help="Общий лимит. 0 означает без лимита.")
    parser.add_argument(
        "--max-products-per-category",
        type=int,
        default=0,
        help="Одинаковый лимит каждой категории. 0 означает без лимита.",
    )
    parser.add_argument("--limit-tires", type=int, default=0, help="Лимит строк в satu_tires.csv.")
    parser.add_argument("--limit-oils", type=int, default=0, help="Лимит строк в satu_oils.csv.")
    parser.add_argument("--limit-filters", type=int, default=0, help="Лимит строк в satu_filters.csv.")
    parser.add_argument("--limit-batteries", type=int, default=0, help="Лимит строк в satu_batteries.csv.")
    parser.add_argument("--max-pages", type=int, default=3, help="Maximum listing pages per category.")
    parser.add_argument("--page-size", type=int, default=48, help="Expected Satu listing page size.")
    parser.add_argument("--output-dir", default="data/satu")
    parser.add_argument("--workers", type=int, default=6, help="Parallel detail requests.")
    parser.add_argument("--timeout", type=float, default=60, help="HTTP timeout in seconds.")
    parser.add_argument("--sleep", type=float, default=0.25, help="Pause between listing pages.")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-sleep", type=float, default=2.0)
    parser.add_argument("--skip-details", action="store_true", help="Only parse listing data; faster but fewer attrs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    requested_categories = [item.strip() for item in args.categories.split(",") if item.strip()]
    unknown = [item for item in requested_categories if item not in CORE_AUTO_CATEGORY_RULES]
    if unknown:
        raise SystemExit(f"Unknown categories: {', '.join(unknown)}")

    started_at = datetime.now(timezone.utc).isoformat()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    print(out_dir)

    state = State()
    raw_count = 0
    detail_errors = 0
    completed = False
    error_message = ""
    raw_path = out_dir / "raw_products.jsonl"
    category_limits = {
        "tires": args.limit_tires,
        "motor_oils": args.limit_oils,
        "filters": args.limit_filters,
        "batteries": args.limit_batteries,
    }

    try:
        print(
            "[satu] Старт: прямые HTTP-запросы, "
            f"workers={args.workers}, details={'нет' if args.skip_details else 'да'}",
            flush=True,
        )
        with SatuHttpClient(timeout=args.timeout) as client, raw_path.open(
            "w", encoding="utf-8"
        ) as raw_file, ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            for category_index, category_key in enumerate(requested_categories, start=1):
                category_flat_count = 0
                category_limit = (
                    category_limits[category_key]
                    or args.max_products_per_category
                    or (args.max_products - len(state.flat_products) if args.max_products else 0)
                )
                category_name = CORE_AUTO_CATEGORY_RULES[category_key]["name"]
                print(
                    f"[satu] [{category_index}/{len(requested_categories)}] {category_name}: "
                    f"лимит={category_limit or 'без лимита'}",
                    flush=True,
                )
                listing_products = iter_listing_products(
                    client,
                    category_key=category_key,
                    page_size_hint=args.page_size,
                    max_pages=args.max_pages,
                    sleep_seconds=args.sleep,
                    retries=args.retries,
                    retry_sleep=args.retry_sleep,
                )
                if category_limit:
                    listing_products = islice(listing_products, category_limit)
                for product_batch in batched(listing_products, max(1, args.workers * 2)):
                    if args.skip_details:
                        detail_results = [(None, None, "")] * len(product_batch)
                    else:
                        detail_results = list(
                            executor.map(
                                lambda product: enrich_detail(
                                    client,
                                    product,
                                    retries=args.retries,
                                    retry_sleep=args.retry_sleep,
                                ),
                                product_batch,
                            )
                        )
                    for listing_product, detail_result in zip(product_batch, detail_results):
                        source_product_id = str(listing_product.get("id") or "")
                        if not source_product_id or source_product_id in state.seen_source_products:
                            continue
                        state.seen_source_products.add(source_product_id)
                        raw_count += 1
                        detail_product, detail_cache, detail_error = detail_result
                        raw_file.write(
                            json.dumps(
                                {
                                    "category_key": category_key,
                                    "listing": listing_product,
                                    "detail": detail_product,
                                    "detail_error": detail_error,
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                        if detail_error:
                            detail_errors += 1
                            print(
                                f"[satu] Детали не получены: {source_product_id}: {detail_error}",
                                flush=True,
                            )

                        state.flat_products.append(
                            build_flat_product(
                                listing_product,
                                detail_product,
                                detail_cache,
                                category_key,
                                parsed_at=started_at,
                            )
                        )
                        category_flat_count += 1
                        if category_flat_count % 25 == 0:
                            print(
                                f"[satu] {category_name}: собрано={category_flat_count}, "
                                f"всего={len(state.flat_products)}",
                                flush=True,
                            )
                        if args.max_products and len(state.flat_products) >= args.max_products:
                            break
                    if args.max_products and len(state.flat_products) >= args.max_products:
                        break
                print(f"[satu] {category_name}: готово, собрано={category_flat_count}", flush=True)
                if args.max_products and len(state.flat_products) >= args.max_products:
                    break
            completed = True
            return 0
    except KeyboardInterrupt:
        error_message = "interrupted"
        raise
    except Exception as exc:
        error_message = str(exc)
        raise
    finally:
        finished_at = datetime.now(timezone.utc).isoformat()
        write_outputs(out_dir, state, raw_count, started_at, finished_at, completed, error_message, detail_errors)
        print(f"[satu] Результаты: {out_dir}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
