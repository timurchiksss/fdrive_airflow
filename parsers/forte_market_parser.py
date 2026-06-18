#!/usr/bin/env python3
"""
Parse ForteMarket auto products through its public JSON API.

The parser uses a regular requests.Session and writes a separate CSV for tires,
oils, filters, and batteries.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any

import requests


SOURCE = "forte_market"
WEB_HOST = "https://market.forte.kz"
API_HOST = "https://apigw.forte.kz/fm"
OBJECT_HOST = "https://object.pscloud.io"

DEFAULT_ATTRIBUTE_GROUPS = {
    "basic": {"id": 1, "name": "Основные характеристики"},
    "dimensions": {"id": 2, "name": "Размеры и вес"},
    "commerce": {"id": 3, "name": "Коммерческие данные"},
    "source": {"id": 4, "name": "Данные источника"},
}

CORE_AUTO_CATEGORY_RULES = {
    2254: {
        "key": "motor_oils",
        "name": "Моторные масла",
        "attributes": [
            "brand",
            "product_line",
            "viscosity",
            "volume_liters",
            "oil_type",
            "engine_type",
            "specification",
            "package_type",
        ],
    },
    984: {
        "key": "batteries",
        "name": "Аккумуляторы",
        "attributes": [
            "brand",
            "capacity_ah",
            "voltage_v",
            "start_current_a",
            "polarity",
            "battery_type",
            "dimensions",
            "terminal_type",
        ],
    },
    1113: {
        "key": "tires",
        "name": "Шины",
        "attributes": [
            "brand",
            "width",
            "profile",
            "diameter",
            "season",
            "load_index",
            "speed_index",
            "runflat",
        ],
    },
    2966: {
        "key": "filters",
        "name": "Фильтры",
        "attributes": [
            "brand",
            "filter_type",
            "compatible_brand",
            "compatible_model",
            "oem_number",
        ],
    },
}

CORE_AUTO_CATEGORY_IDS = set(CORE_AUTO_CATEGORY_RULES)

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
    "petronas",
    "yacco",
    "ngn",
    "cworks",
    "g-energy",
    "viatti",
    "cordiant",
    "nokian",
    "ikon tyres",
    "mutlu",
    "akom",
    "tyumen",
    "bosch",
    "varta",
    "hankook",
    "bridgestone",
    "michelin",
    "goodyear",
    "pirelli",
    "continental",
    "yokohama",
    "kumho",
    "nexen",
    "sakura",
    "mann-filter",
    "mahle",
    "filtron",
    "wunscher",
    "rocket",
    "bars",
    "exide",
    "racer",
    "wewatt",
    "furukawa",
    "husky",
]

ATTRIBUTE_ALIASES = {
    "бренд": "brand",
    "brand": "brand",
    "емкость, л": "volume_liters",
    "объем, л": "volume_liters",
    "объём, л": "volume_liters",
    "вязкость": "viscosity",
    "тип": "oil_type",
    "двигатель": "engine_type",
    "диаметр": "diameter",
    "ширина": "width",
    "профиль": "profile",
    "сезон": "season",
    "индекс нагрузки": "load_index",
    "индекс скорости": "speed_index",
    "емкость аккумулятора": "capacity_ah",
    "емкость аккумулятора, aч": "capacity_ah",
    "емкость аккумулятора, ач": "capacity_ah",
    "емкость": "capacity_ah",
    "емкость, а/ч": "capacity_ah",
    "емкость, ач": "capacity_ah",
    "напряжение": "voltage_v",
    "напряжение, в": "voltage_v",
    "напряжение аккумулятора": "voltage_v",
    "пусковой ток": "start_current_a",
    "пусковой ток, a": "start_current_a",
    "пусковой ток, а": "start_current_a",
    "полярность": "polarity",
    "полярность аккумулятора": "polarity",
    "тип аккумулятора": "battery_type",
    "тип клемм": "terminal_type",
    "типоразмер": "dimensions",
    "размер": "dimensions",
    "runflat": "runflat",
    "run flat": "runflat",
    "тип фильтра": "filter_type",
    "тип автомобильного фильтра": "filter_type",
    "oem номер": "oem_number",
    "oem-номер": "oem_number",
    "oem": "oem_number",
    "артикул oem": "oem_number",
    "артикул производителя": "oem_number",
    "артикул_производителя": "oem_number",
    "совместимая марка": "compatible_brand",
    "марка автомобиля": "compatible_brand",
    "совместимая модель": "compatible_model",
    "модель автомобиля": "compatible_model",
    "спецификация": "specification",
    "допуск": "specification",
    "упаковка": "package_type",
    "тип упаковки": "package_type",
}

RE_AD_WORDS = re.compile(
    r"\b(купить|акция|скидка|рассрочка|оригинал|новинка|доставка|sale|new)\b",
    re.IGNORECASE,
)
RE_SPACES = re.compile(r"\s+")
RE_VOLUME = re.compile(
    r"(?<![0-9A-Za-zА-Яа-я])(?P<value>\d+(?:[.,]\d+)?)\s*(?:л|l|литр(?:а|ов)?)\b",
    re.IGNORECASE,
)
RE_VISCOSITY = re.compile(r"\b(?P<value>\d{1,2}w[-\s]?\d{2})\b", re.IGNORECASE)
RE_TIRE = re.compile(r"\b(?P<width>\d{3})/(?P<profile>\d{2})\s*r(?P<diameter>\d{2})\b", re.IGNORECASE)
RE_BATTERY_CAPACITY = re.compile(r"\b(?P<value>\d{1,3})\s*(?:ah|а/ч|ач|а\.ч\.?)\b", re.IGNORECASE)
RE_VOLTAGE = re.compile(r"\b(?P<value>6|12|24)\s*(?:v|в)\b", re.IGNORECASE)
RE_START_CURRENT = re.compile(r"\b(?P<value>\d{3,4})\s*(?:a|а)\b", re.IGNORECASE)
RE_LOAD_SPEED = re.compile(r"\b(?P<load>\d{2,3})(?P<speed>[A-ZА-Я])\b", re.IGNORECASE)
RE_OEM = re.compile(r"\b(?:OEM[:\s-]*)?(?P<value>[A-ZА-Я0-9][A-ZА-Я0-9./-]{4,})\b", re.IGNORECASE)
RE_OIL_SPEC = re.compile(r"\b(?P<value>(?:A\\d/B\\d|C\\d|SP|SN|SM|SL|CF|GF-\\d)(?:[/\\s-]*(?:A\\d/B\\d|C\\d|SP|SN|SM|SL|CF|GF-\\d))*)\b", re.IGNORECASE)

GENERIC_BRAND_WORDS = {
    "синтетическое",
    "полусинтетическое",
    "минеральное",
    "моторное",
    "масло",
    "аккумулятор",
    "шина",
    "фильтр",
}


@dataclass
class State:
    categories: dict[str, dict[str, Any]] = field(default_factory=dict)
    flat_products: list[dict[str, Any]] = field(default_factory=list)
    category_uid_to_int: dict[str, int] = field(default_factory=dict)
    seen_source_products: set[str] = field(default_factory=set)
    next_category_id: int = 1


class ForteApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: Any):
        super().__init__(f"API {method} {path} failed with {status}: {body}")
        self.method = method
        self.path = path
        self.status = status
        self.body = body


class ForteNetworkError(RuntimeError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def source_sku_id(source_uid: str, source_product_id: str) -> str:
    source_key = source_uid or source_product_id
    return f"{SOURCE}:{source_key}"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = RE_SPACES.sub(" ", text)
    return text.strip()


def normalize_attr_name(title: str) -> str:
    key = clean_text(title).lower()
    key = ATTRIBUTE_ALIASES.get(key, key)
    key = re.sub(r"[^0-9a-zа-яё_]+", "_", key, flags=re.IGNORECASE)
    key = key.strip("_").lower()
    return key or "unknown_attribute"


def normalize_brand(raw_name: str, explicit: str = "") -> str:
    explicit_clean = clean_text(explicit)
    if (
        explicit_clean
        and explicit_clean.lower() not in GENERIC_BRAND_WORDS
        and not re.match(r"(?i)^рц[-_]*\d+$", explicit_clean)
    ):
        return explicit_clean.title()
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
        "аккумулятор",
        "фильтр",
        "vip",
    } | GENERIC_BRAND_WORDS
    for token in tokens:
        if re.match(r"(?i)^рц[-_]*\d+$", token):
            continue
        if token.lower() not in skip and re.search(r"[A-Za-zА-Яа-я]", token):
            return token.strip(" ,.;:").title()
    return ""


def normalize_category_key(category_id: int) -> str | None:
    rule = CORE_AUTO_CATEGORY_RULES.get(category_id)
    return rule["key"] if rule else None


def allowed_attributes_for_category(category_id: int) -> list[str] | None:
    rule = CORE_AUTO_CATEGORY_RULES.get(category_id)
    return list(rule["attributes"]) if rule else None


def infer_product_line(name: str, brand: str) -> str:
    text = clean_text(name)
    if brand:
        text = re.sub(rf"(?i)\b{re.escape(brand)}\b", " ", text)
    text = re.sub(r"(?i)\b(моторное|масло|синтетическое|полусинтетическое|минеральное)\b", " ", text)
    text = RE_VISCOSITY.sub(" ", text)
    text = RE_VOLUME.sub(" ", text)
    text = RE_BATTERY_CAPACITY.sub(" ", text)
    text = re.sub(r"(?i)\b\d{2,3}\s*(?:ah|aч|ач|аh|а/ч|a/h)\b", " ", text)
    text = re.sub(r"(?i)\bрц[-_]*\d+\b", " ", text)
    text = re.sub(r"(?i)\b6\s*[сc]т[- ]?\b", " ", text)
    text = RE_SPACES.sub(" ", text).strip(" ,.;:-")
    return text


def format_viscosity(value: str) -> str:
    match = RE_VISCOSITY.search(clean_text(value))
    raw = match.group("value") if match else clean_text(value)
    return raw.upper().replace(" ", "").replace("W", "W-").replace("W--", "W-")


def format_volume_liters(value: str) -> str:
    text = clean_text(value).replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return text
    number = match.group(0)
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    return f"{number}L"


def smart_case_token(token: str) -> str:
    token = token.strip(" ,.;:!?")
    if not token:
        return ""
    if any(ch.isdigit() for ch in token):
        return token.upper()
    if token.isupper() and len(token) > 1:
        return token
    return token[:1].upper() + token[1:]


def clean_line_value(value: str, brand: str = "") -> str:
    text = clean_text(value).replace("ё", "е").replace("Ё", "Е")
    text = re.sub(r"[™®©!]+", " ", text)
    text = RE_AD_WORDS.sub(" ", text)
    if brand:
        text = re.sub(rf"(?i)(?<!\w){re.escape(brand)}(?!\w)", " ", text)
    text = re.sub(
        r"(?i)\b(масло|моторное|синтетическое|полусинтетическое|минеральное|аккумулятор|шина|шины|фильтр|автомобильный|автомобильная|автомобильное|автомобильные)\b",
        " ",
        text,
    )
    text = RE_VISCOSITY.sub(" ", text)
    text = RE_VOLUME.sub(" ", text)
    text = RE_BATTERY_CAPACITY.sub(" ", text)
    text = re.sub(r"(?i)\b\d{2,3}\s*(?:ah|aч|ач|аh|а/ч|a/h)\b", " ", text)
    text = re.sub(r"(?i)\bрц[-_]*\d+\b", " ", text)
    text = re.sub(r"(?i)\b6\s*[сc]т[- ]?\b", " ", text)
    text = RE_SPACES.sub(" ", text).strip(" ,.;:")
    tokens: list[str] = []
    seen: set[str] = set()
    for token in text.split():
        normalized = token.strip(" ,.;:!?")
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        if not re.search(r"[0-9A-Za-zА-Яа-я]", normalized) and normalized not in {"+/-", "-/+"}:
            continue
        seen.add(key)
        tokens.append(smart_case_token(normalized))
    return " ".join(tokens)


def clean_tire_line_value(value: str, brand: str = "") -> str:
    text = clean_line_value(value, brand)
    text = RE_TIRE.sub(" ", text)
    text = re.sub(r"\b\d{3}/\d{2}\s*R\d{2}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{2,3}\s*[A-ZА-Я]\d?\b(?:\s*\([^)]*\))?", " ", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(?i)\b(летняя|летние|зимняя|зимние|всесезонная|всесезонные|без|шипов|шипованная|runflat|run flat)\b",
        " ",
        text,
    )
    return RE_SPACES.sub(" ", text).strip(" ,.;:")


def format_load_speed(load_value: str, speed_value: str) -> str:
    load_match = re.search(r"\d{2,3}", clean_text(load_value))
    speed_match = re.search(r"[A-ZА-Я]\d?", clean_text(speed_value), flags=re.IGNORECASE)
    return f"{load_match.group(0) if load_match else ''}{speed_match.group(0).upper() if speed_match else ''}".strip()


def infer_filter_type(name: str) -> str:
    lowered = name.lower()
    options = {
        "масля": "oil",
        "воздуш": "air",
        "салон": "cabin",
        "топлив": "fuel",
        "фильтр акпп": "transmission",
    }
    for marker, value in options.items():
        if marker in lowered:
            return value
    return ""


def normalize_product_name(name: str, brand: str, attrs: dict[str, str]) -> str:
    derived_attrs = extract_derived_attrs(name)
    attrs = {**derived_attrs, **{key: value for key, value in attrs.items() if value}}
    clean_brand = normalize_brand(name, brand)
    parts: list[str] = []
    if clean_brand:
        parts.append(clean_brand)

    if attrs.get("product_line") or attrs.get("viscosity") or attrs.get("volume_liters"):
        line = clean_line_value(attrs.get("product_line") or name, clean_brand)
        if line:
            parts.append(line)
        if attrs.get("viscosity"):
            parts.append(format_viscosity(attrs["viscosity"]))
        if attrs.get("volume_liters"):
            parts.append(format_volume_liters(attrs["volume_liters"]))
    elif attrs.get("capacity_ah") or attrs.get("voltage_v") or attrs.get("start_current_a"):
        line = clean_line_value(name, clean_brand)
        if line:
            parts.append(line)
        if attrs.get("capacity_ah"):
            parts.append(f"{normalize_numeric_text(attrs['capacity_ah'])}Ah")
        if attrs.get("voltage_v"):
            parts.append(f"{normalize_numeric_text(attrs['voltage_v'])}V")
        if attrs.get("start_current_a"):
            parts.append(f"{normalize_numeric_text(attrs['start_current_a'])}A")
    elif attrs.get("width") or attrs.get("diameter"):
        tire_size = ""
        if attrs.get("width") and attrs.get("profile") and attrs.get("diameter"):
            tire_size = f"{attrs['width']}/{attrs['profile']} {attrs['diameter']}"
        elif attrs.get("width") and attrs.get("diameter"):
            tire_size = f"{attrs['width']} {attrs['diameter']}"
        line = clean_tire_line_value(name, clean_brand)
        if line:
            parts.append(line)
        if tire_size:
            parts.append(tire_size)
        if attrs.get("load_index") or attrs.get("speed_index"):
            load_speed = format_load_speed(attrs.get("load_index", ""), attrs.get("speed_index", ""))
            if load_speed:
                parts.append(load_speed)
        if attrs.get("runflat"):
            parts.append("RunFlat")
    else:
        line = clean_line_value(name, clean_brand)
        if line:
            parts.append(line)

    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        part = clean_text(part).strip(" ,.;:")
        key = part.lower()
        if part and key not in seen:
            result.append(part)
            seen.add(key)
    return RE_SPACES.sub(" ", " ".join(result)).strip()


def extract_derived_attrs(name: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    volume = RE_VOLUME.search(name)
    if volume:
        attrs["volume_liters"] = volume.group("value").replace(",", ".")
    viscosity = RE_VISCOSITY.search(name)
    if viscosity:
        attrs["viscosity"] = viscosity.group("value").upper().replace(" ", "").replace("W", "W-").replace("W--", "W-")
    tire = RE_TIRE.search(name)
    if tire:
        attrs["width"] = tire.group("width")
        attrs["profile"] = tire.group("profile")
        attrs["diameter"] = f"R{tire.group('diameter')}"
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
    if tire and load_speed:
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
    if "полусинтет" in lowered:
        attrs["oil_type"] = "semi_synthetic"
    elif "синтет" in lowered:
        attrs["oil_type"] = "synthetic"
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
    if "6ст" in lowered or "6 ст" in lowered:
        attrs["voltage_v"] = "12"
    return attrs


def canonical_value(char: dict[str, Any]) -> str:
    values = char.get("Values")
    if isinstance(values, list):
        return "; ".join(clean_text(v) for v in values if clean_text(v))
    return clean_text(char.get("Value"))


def normalize_numeric_text(value: str) -> str:
    match = re.search(r"\d+(?:[.,]\d+)?", value)
    return match.group(0).replace(",", ".") if match else value


class ForteHttpClient:
    def __init__(self, *, timeout: float = 60):
        self.timeout = timeout
        self._local = threading.local()
        self._sessions: list[requests.Session] = []
        self._sessions_lock = threading.Lock()

    def __enter__(self) -> "ForteHttpClient":
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
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": WEB_HOST,
                "Referer": WEB_HOST + "/",
            }
        )
        self._local.session = session
        with self._sessions_lock:
            self._sessions.append(session)
        return session

    def __exit__(self, exc_type, exc, tb) -> None:
        for session in self._sessions:
            session.close()

    def api_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._api("GET", path, None, params)

    def api_post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._api("POST", path, payload, None)

    def _api(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        params: dict[str, Any] | None,
    ) -> Any:
        url = API_HOST + path
        try:
            response = self._session().request(
                method,
                url,
                params=params,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ForteNetworkError(f"API {method} {path} request failed: {exc}") from exc
        try:
            body = response.json() if response.text else None
        except ValueError:
            body = response.text
        if not response.ok:
            raise ForteApiError(method, path, response.status_code, body)
        return body


def register_category(
    state: State,
    *,
    uid: str,
    short_id: int | str | None,
    title: str,
    parent_uid: str = "",
    level: int = 1,
    is_leaf: bool = False,
) -> int:
    if not uid:
        uid = f"short:{short_id}:{title}"
    if uid not in state.category_uid_to_int:
        state.category_uid_to_int[uid] = int(short_id or state.next_category_id)
        if state.category_uid_to_int[uid] <= 0:
            state.category_uid_to_int[uid] = state.next_category_id
        state.next_category_id = max(state.next_category_id, state.category_uid_to_int[uid] + 1)

    category_id = state.category_uid_to_int[uid]
    parent_id = state.category_uid_to_int.get(parent_uid) if parent_uid else None
    state.categories[str(category_id)] = {
        "category_id": category_id,
        "name": clean_text(title),
        "level": level,
        "parent_category_id": parent_id or "",
        "parent_category": state.categories.get(str(parent_id), {}).get("name", "") if parent_id else "",
        "is_leaf": bool(is_leaf),
        "status": "active",
        "source_uid": uid,
    }
    return category_id


def collect_categories(client: ForteHttpClient, state: State, root_slug: str) -> str:
    root = client.api_get(f"/api/v4/catalogs/fulldata/slug/{root_slug}", {"lite": "true"})
    category = root["category"]
    root_uid = category["uid"]
    register_category(
        state,
        uid=root_uid,
        short_id=category.get("short_id"),
        title=category.get("title", root_slug),
        level=category.get("depth", 1) or 1,
        is_leaf=False,
    )

    first_level = client.api_get(f"/api/v4/catalogs/{root_uid}/childs/1", {"visible": "true"})
    for parent_uid, items in first_level.items():
        if parent_uid in {"head", "root"} or not isinstance(items, list):
            continue
        for item in items:
            register_category(
                state,
                uid=item.get("id", ""),
                short_id=item.get("shortID"),
                title=item.get("title", ""),
                parent_uid=root_uid,
                level=2,
                is_leaf=False,
            )

    children = client.api_get(f"/api/v4/catalogs/{root_uid}/childs/10", {"visible": "true"})
    for parent_uid, items in children.items():
        if parent_uid in {"head", "root"} or not isinstance(items, list):
            continue
        parent_known = parent_uid in state.category_uid_to_int
        if not parent_known:
            register_category(
                state,
                uid=parent_uid,
                short_id=None,
                title=parent_uid,
                parent_uid=root_uid,
                level=2,
                is_leaf=False,
            )
        for item in items:
            parent_level = int(state.categories.get(str(state.category_uid_to_int.get(parent_uid, 0)), {}).get("level") or 1)
            is_root_child = parent_uid == root_uid
            register_category(
                state,
                uid=item.get("id", ""),
                short_id=item.get("shortID"),
                title=item.get("title", ""),
                parent_uid=parent_uid,
                level=parent_level + 1,
                is_leaf=not is_root_child,
            )
    return root_uid


def leaf_category_uids(state: State, root_uid: str) -> list[str]:
    leaves = [
        row["source_uid"]
        for row in state.categories.values()
        if row.get("is_leaf") and row.get("source_uid") and row.get("source_uid") != root_uid
    ]
    return sorted(set(leaves), key=lambda uid: state.category_uid_to_int.get(uid, 0))


def keep_only_target_categories(state: State, target_uids: list[str]) -> None:
    target_ids = {state.category_uid_to_int[uid] for uid in target_uids if uid in state.category_uid_to_int}
    state.categories = {
        str(category_id): row
        for category_id, row in ((int(key), value) for key, value in state.categories.items())
        if category_id in target_ids
    }
    state.category_uid_to_int = {
        uid: category_id for uid, category_id in state.category_uid_to_int.items() if category_id in target_ids
    }


def category_id_for_product(state: State, product: dict[str, Any]) -> int:
    categories = product.get("categories_array") or []
    for uid in reversed(categories):
        if uid in state.category_uid_to_int:
            return state.category_uid_to_int[uid]
    if categories:
        return register_category(
            state,
            uid=categories[-1],
            short_id=None,
            title=categories[-1],
            level=len(categories),
            is_leaf=True,
        )
    return 0


def build_source_url(product: dict[str, Any]) -> str:
    slug = product.get("slug")
    uid = product.get("uid")
    if uid and slug:
        return f"{WEB_HOST}/items/{uid}/{slug}"
    if slug:
        return f"{WEB_HOST}/items/{slug}"
    return WEB_HOST


def media_urls(product: dict[str, Any]) -> list[str]:
    urls = []
    for media in product.get("media") or []:
        url = media.get("media_url")
        if not url:
            continue
        urls.append(url if url.startswith("http") else OBJECT_HOST + url)
    return urls


def ingest_product(
    state: State,
    product: dict[str, Any],
    detail: dict[str, Any] | None,
    parsed_at: str,
    city: str,
) -> bool:
    showcase = (detail or {}).get("showcase") or product
    chars = (detail or {}).get("characteristics") or []
    name = clean_text(showcase.get("name") or product.get("name"))
    category_id = category_id_for_product(state, showcase)
    if category_id not in CORE_AUTO_CATEGORY_IDS:
        return False
    category_name = state.categories.get(str(category_id), {}).get("name", "")
    allowed_attrs = allowed_attributes_for_category(category_id) or []

    raw_attrs: dict[str, str] = {}
    for char in chars:
        attr_name = normalize_attr_name(char.get("Title", ""))
        value = canonical_value(char)
        if attr_name and value:
            if attr_name in {"capacity_ah", "voltage_v", "start_current_a"}:
                value = normalize_numeric_text(value)
            raw_attrs[attr_name] = value

    derived = extract_derived_attrs(name)
    raw_attrs = {**derived, **raw_attrs}
    brand = normalize_brand(name, raw_attrs.get("brand", ""))
    if brand:
        raw_attrs["brand"] = brand
    if category_id == 2254:
        product_line = infer_product_line(name, brand)
        if product_line:
            raw_attrs["product_line"] = product_line
        if raw_attrs.get("volume_liters") and not raw_attrs.get("package_type"):
            raw_attrs["package_type"] = "bottle"
    if category_id == 2966:
        filter_type = infer_filter_type(name)
        if filter_type:
            raw_attrs["filter_type"] = filter_type
    if allowed_attrs is not None:
        raw_attrs = {key: value for key, value in raw_attrs.items() if key in allowed_attrs and value}

    source_product_id = str(showcase.get("short_id") or product.get("short_id") or showcase.get("uid"))
    source_uid = str(showcase.get("uid") or product.get("uid") or "")
    sku_id = source_sku_id(source_uid, source_product_id)
    normalized_name = normalize_product_name(name, brand, raw_attrs)
    source_url = build_source_url(showcase)
    images = media_urls(showcase) or media_urls(product)
    min_price = None
    skus = showcase.get("skus") or []
    if skus:
        min_price_data = skus[0].get("min_price")
        if isinstance(min_price_data, dict):
            min_price = min_price_data.get(city) or min_price_data.get("KZ")
        elif min_price_data:
            min_price = min_price_data
    price = product.get("product_price") or min_price
    old_price = product.get("old_product_price") or 0
    in_stock = bool(showcase.get("in_stock", product.get("in_stock", False)))
    normalized_description = clean_text(showcase.get("description") or showcase.get("short_description") or "")
    rating = product.get("aggs_rating")
    reviews_count = product.get("reviews_count")

    dimensions = showcase.get("dimensions") or {}
    flat_row = {
        "sku_id": sku_id,
        "source": SOURCE,
        "source_product_id": source_product_id,
        "source_uid": source_uid,
        "source_url": source_url,
        "slug": showcase.get("slug") or product.get("slug") or "",
        "category_id": category_id,
        "category": category_name,
        "product_name": name,
        "normalized_name": normalized_name,
        "description": normalized_description[:2000],
        "price": price if price is not None else "",
        "old_price": old_price,
        "currency": "KZT",
        "availability": "in_stock" if in_stock else "out_of_stock",
        "city": city,
        "parsed_at": parsed_at,
        "image_urls": json.dumps(images, ensure_ascii=False),
        "rating": rating if rating is not None else "",
        "reviews_count": reviews_count if reviews_count is not None else "",
        "seller_count": len(skus),
        "weight": showcase.get("weight") or product.get("weight") or "",
    }
    for attr_name in allowed_attrs:
        flat_row[attr_name] = raw_attrs.get(attr_name, "")
    if "dimensions" in allowed_attrs and dimensions:
        flat_row["dimensions"] = flat_row.get("dimensions") or "x".join(
            str(dimensions[key]) for key in ("length", "width", "height") if dimensions.get(key) not in (None, "")
        )
    state.flat_products.append(flat_row)
    return True


def fetch_detail(client: ForteHttpClient, product: dict[str, Any], city: str) -> dict[str, Any] | None:
    slug = product.get("slug")
    uid = product.get("uid")
    candidates = []
    if slug:
        candidates.append(("/api/v4/products/showcase/fulldata/slug/" + slug, {"cityid": city}))
    if uid:
        candidates.append(("/api/v4/products/showcase/fulldata/" + uid, {"cityid": city}))
    for path, params in candidates:
        try:
            return client.api_get(path, params)
        except Exception:
            continue
    return None


def iter_products(
    client: ForteHttpClient,
    *,
    category_uid: str,
    city: str,
    page_size: int,
    max_products: int,
    sleep_s: float,
    start_offset: int,
    retries: int,
    retry_sleep: float,
):
    fetched = 0
    offset = start_offset
    while True:
        payload = {"from": offset, "size": page_size, "category": category_uid, "city": city}
        data = None
        for attempt in range(retries + 1):
            try:
                data = client.api_post("/api/v4/products/showcase/filter-lite", payload)
                break
            except ForteApiError as exc:
                retryable = exc.status in {429, 500, 502, 503, 504}
                if not retryable or attempt >= retries:
                    raise
                delay = retry_sleep * (2 ** attempt)
                print(
                    f"API status {exc.status} at category={category_uid} offset={offset}; "
                    f"retry {attempt + 1}/{retries} in {delay:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
            except ForteNetworkError as exc:
                if attempt >= retries:
                    raise
                delay = retry_sleep * (2 ** attempt)
                print(
                    f"Network error at category={category_uid} offset={offset}: {exc}; "
                    f"retry {attempt + 1}/{retries} in {delay:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
        if data is None:
            break
        products = data.get("products") or []
        total = data.get("total_hits") or 0
        print(
            f"[forte] listing offset={offset}: получено={len(products)}, всего={total or 'неизвестно'}",
            flush=True,
        )
        if not products:
            break
        for product in products:
            yield product
            fetched += 1
            if max_products and fetched >= max_products:
                return
        offset += len(products)
        if total and offset >= total:
            break
        if sleep_s:
            time.sleep(sleep_s)


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
        "article_sku": row.get("source_product_id", ""),
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
                "model_name": row.get("product_line", ""),
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
                "Класс ACEA": "",
                "Допуски": "",
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
                "additional_information": row.get("description", ""),
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
                "features": row.get("description", ""),
                "length": "",
                "width": "",
                "height": "",
            }
        )
    return common


def write_outputs(
    out_dir: Path,
    state: State,
    raw_count: int,
    started_at: str,
    finished_at: str,
    completed: bool,
    error: str,
    *,
    stream_raw_db: bool = False,
    raw_schema: str = "raw",
    load_id: str = "",
    create_database: bool = False,
    maintenance_database: str = "postgres",
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    output_counts: dict[str, int] = {}
    if stream_raw_db:
        scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from normalize_catalog_csvs import CANONICALIZERS, SCHEMAS  # noqa: PLC0415
        from streaming_raw_writer import StreamingRawWriter  # noqa: PLC0415

        writer = StreamingRawWriter.from_env(
            schema=raw_schema,
            load_id=load_id or now_utc(),
            source_file="forte_market_stream",
            create_database=create_database,
            maintenance_database=maintenance_database,
        )
        try:
            for category_id, rule in CORE_AUTO_CATEGORY_RULES.items():
                output_key = "oils" if rule["key"] == "motor_oils" else rule["key"]
                rows = [row for row in state.flat_products if row.get("category_id") == category_id]
                canonical_rows = [
                    CANONICALIZERS[output_key](output_row(row, output_key), "forte_market")
                    for row in rows
                ]
                table = f"forte_market_{output_key}"
                output_counts[output_key] = writer.write_rows(table, canonical_rows, SCHEMAS[output_key])
                print(f"[raw-db] {raw_schema}.{table}: +{output_counts[output_key]}, load_id={writer.load_id}", flush=True)
        finally:
            writer.close()
    else:
        for category_id, rule in CORE_AUTO_CATEGORY_RULES.items():
            output_key = "oils" if rule["key"] == "motor_oils" else rule["key"]
            rows = [row for row in state.flat_products if row.get("category_id") == category_id]
            output_counts[output_key] = write_csv(
                out_dir / f"forte_{output_key}.csv",
                (output_row(row, output_key) for row in rows),
                GROUP_OUTPUT_COLUMNS[output_key],
            )

    summary = {
        "source": SOURCE,
        "started_at": started_at,
        "finished_at": finished_at,
        "raw_products": raw_count,
        "categories": len(state.categories),
        "unique_source_products": len(state.seen_source_products),
        "flat_products": len(state.flat_products),
        "output_counts": output_counts,
        "completed": completed,
        "error": error,
    }
    (out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse ForteMarket products using direct HTTP API requests.")
    parser.add_argument(
        "--category-slug",
        default="avtotovary-2188",
        help="Root ForteMarket category slug used to find the four target auto categories.",
    )
    parser.add_argument("--city", default="KZ", help="ForteMarket city code, e.g. KZ, KZ-ALA, KZ-AST.")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument(
        "--max-products",
        type=int,
        default=0,
        help="Общий лимит товаров. 0 означает без общего лимита.",
    )
    parser.add_argument(
        "--max-products-per-category",
        type=int,
        default=0,
        help="Одинаковый лимит для каждой категории. 0 означает без лимита.",
    )
    parser.add_argument("--limit-tires", type=int, default=0, help="Лимит строк в forte_tires.csv.")
    parser.add_argument("--limit-oils", type=int, default=0, help="Лимит строк в forte_oils.csv.")
    parser.add_argument("--limit-filters", type=int, default=0, help="Лимит строк в forte_filters.csv.")
    parser.add_argument("--limit-batteries", type=int, default=0, help="Лимит строк в forte_batteries.csv.")
    parser.add_argument("--start-offset", type=int, default=0, help="Start offset inside each requested category.")
    parser.add_argument("--output-dir", default="data/forte_market")
    parser.add_argument("--timeout", type=float, default=60, help="HTTP timeout in seconds.")
    parser.add_argument("--workers", type=int, default=6, help="Parallel detail requests.")
    parser.add_argument("--sleep", type=float, default=0.25, help="Pause between listing pages.")
    parser.add_argument("--retries", type=int, default=5, help="Retries for transient API errors.")
    parser.add_argument("--retry-sleep", type=float, default=5.0, help="Initial retry sleep in seconds.")
    parser.add_argument("--skip-details", action="store_true", help="Only parse listing data; faster but fewer attrs.")
    parser.add_argument("--stream-raw-db", action="store_true", help="Write canonical rows into raw Postgres instead of CSV.")
    parser.add_argument("--raw-schema", default="raw")
    parser.add_argument("--load-id", default="")
    parser.add_argument("--create-database", action="store_true")
    parser.add_argument("--maintenance-database", default="postgres")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started_at = now_utc()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) / run_id
    raw_path = out_dir / "raw_products.jsonl"
    state = State()
    raw_count = 0
    completed = False
    error_message = ""
    category_limits = {
        "tires": args.limit_tires,
        "oils": args.limit_oils,
        "filters": args.limit_filters,
        "batteries": args.limit_batteries,
    }

    try:
        print(
            "[forte] Старт: прямые HTTP-запросы, "
            f"page_size={args.page_size}, workers={args.workers}, "
            f"details={'нет' if args.skip_details else 'да'}",
            flush=True,
        )
        with ForteHttpClient(timeout=args.timeout) as client:
            print(f"[forte] Получаю дерево категорий: {args.category_slug}", flush=True)
            category_uid = collect_categories(client, state, args.category_slug)
            category_targets = [category_uid]
            leaves = leaf_category_uids(state, category_uid)
            if leaves:
                category_targets = leaves
            category_targets = [
                uid
                for uid in category_targets
                if state.category_uid_to_int.get(uid) in CORE_AUTO_CATEGORY_IDS
            ]
            target_names = ", ".join(
                state.categories.get(str(state.category_uid_to_int.get(uid)), {}).get("name", uid)
                for uid in category_targets
            )
            print(f"[forte] Найдены категории: {target_names}", flush=True)
            if not category_targets:
                raise RuntimeError(
                    "No target categories found. Expected motor oils, batteries, tires, and auto filters under "
                    f"{args.category_slug}."
                )
            keep_only_target_categories(state, category_targets)
            out_dir.mkdir(parents=True, exist_ok=True)
            with raw_path.open("w", encoding="utf-8") as raw_file, ThreadPoolExecutor(
                max_workers=max(1, args.workers)
            ) as executor:
                for idx, target_uid in enumerate(category_targets, start=1):
                    category_id = state.category_uid_to_int.get(target_uid, 0)
                    category_name = state.categories.get(str(category_id), {}).get("name", target_uid)
                    category_rule = CORE_AUTO_CATEGORY_RULES[category_id]
                    category_key = "oils" if category_rule["key"] == "motor_oils" else category_rule["key"]
                    category_limit = (
                        category_limits[category_key]
                        or args.max_products_per_category
                        or (args.max_products - raw_count if args.max_products else 0)
                    )
                    category_count = 0
                    print(
                        f"[forte] [{idx}/{len(category_targets)}] {category_name}: "
                        f"лимит={category_limit or 'без лимита'}",
                        flush=True,
                    )
                    products = iter_products(
                        client,
                        category_uid=target_uid,
                        city=args.city,
                        page_size=args.page_size,
                        max_products=category_limit,
                        sleep_s=args.sleep,
                        start_offset=args.start_offset,
                        retries=args.retries,
                        retry_sleep=args.retry_sleep,
                    )
                    for product_batch in batched(products, max(1, args.workers * 2)):
                        if args.skip_details:
                            details = [None] * len(product_batch)
                        else:
                            details = list(
                                executor.map(
                                    lambda product: fetch_detail(client, product, args.city),
                                    product_batch,
                                )
                            )
                        for product, detail in zip(product_batch, details):
                            source_key = str(product.get("uid") or product.get("short_id") or product.get("slug"))
                            if source_key in state.seen_source_products:
                                continue
                            state.seen_source_products.add(source_key)

                            if detail is None and not args.skip_details:
                                print(f"[forte] Детали не получены: {source_key}", file=sys.stderr, flush=True)
                            parsed_at = now_utc()
                            raw_file.write(
                                json.dumps(
                                    {
                                        "category_uid": target_uid,
                                        "product": product,
                                        "detail": detail,
                                        "parsed_at": parsed_at,
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                            if not ingest_product(state, product, detail, parsed_at, args.city):
                                continue
                            raw_count += 1
                            category_count += 1
                            if category_count % 25 == 0:
                                print(
                                    f"[forte] {category_name}: собрано={category_count}, всего={raw_count}",
                                    flush=True,
                                )
                            if args.max_products and raw_count >= args.max_products:
                                break
                        if args.max_products and raw_count >= args.max_products:
                            break
                    print(f"[forte] {category_name}: готово, собрано={category_count}", flush=True)
                    if args.max_products and raw_count >= args.max_products:
                        break
            completed = True
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        finished_at = now_utc()
        write_outputs(
            out_dir,
            state,
            raw_count,
            started_at,
            finished_at,
            completed,
            error_message,
            stream_raw_db=args.stream_raw_db,
            raw_schema=args.raw_schema,
            load_id=args.load_id,
            create_database=args.create_database,
            maintenance_database=args.maintenance_database,
        )
        print(f"[forte] Результаты: {out_dir}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
