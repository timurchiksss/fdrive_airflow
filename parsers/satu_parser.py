#!/usr/bin/env python3
"""
Parse Satu.kz auto products from the four target categories into one flat CSV.

The scraper uses CloakBrowser for the browsing/session layer and reads Satu's
server-rendered Apollo cache from listing and product pages.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from cloakbrowser import launch
except ImportError as exc:  # pragma: no cover - human-facing setup error
    raise SystemExit(
        "cloakbrowser is not installed. Run: python3 -m pip install -r requirements.txt"
    ) from exc


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
        ],
    },
}

CATEGORY_ID_TO_KEY = {
    category_id: key
    for key, rule in CORE_AUTO_CATEGORY_RULES.items()
    for category_id in rule["category_ids"]
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
    "стандарт acea": "specification",
    "допуск": "specification",
    "допуски": "specification",
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
    "диаметр": "diameter",
    "сезонность шин": "season",
    "сезон": "season",
    "индекс нагрузки": "load_index",
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


class SatuBrowserClient:
    def __init__(self, *, headless: bool, slow_mo_ms: int, humanize: bool, direct_http: bool):
        self.headless = headless
        self.slow_mo_ms = slow_mo_ms
        self.humanize = humanize
        self.direct_http = direct_http
        self.browser = None
        self.page = None

    def __enter__(self) -> "SatuBrowserClient":
        if self.direct_http:
            return self
        os.environ.setdefault("CLOAKBROWSER_CACHE_DIR", str((Path.cwd() / ".cloakbrowser").resolve()))
        kwargs: dict[str, Any] = {
            "headless": self.headless,
            "humanize": self.humanize,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if self.slow_mo_ms:
            kwargs["slow_mo"] = self.slow_mo_ms
        self.browser = launch(**kwargs)
        self.page = self.browser.new_page()
        self.page.set_default_timeout(45_000)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.browser:
            self.browser.close()

    def fetch_text(self, url: str) -> str:
        if self.direct_http:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.read().decode("utf-8", errors="replace")

        assert self.page is not None
        response = self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        status = response.status if response else 0
        if status >= 400:
            raise SatuParseError(f"GET {url} failed with {status}")
        return self.page.content()


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

    attrs = extract_derived_attrs(name)
    dimension_parts: dict[str, str] = {}
    for attr in product.get("attributes") or []:
        raw_attr_name = clean_text(attr.get("name", ""))
        attr_name = normalize_attr_name(raw_attr_name)
        value = attribute_values(attr, cache)
        if category_key == "batteries":
            raw_key = raw_attr_name.lower().replace("ё", "е")
            if raw_key in {"длина", "ширина", "высота"}:
                dimension_parts[raw_key] = normalize_numeric_text(value)
                continue
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

    row = {
        "sku_id": f"{SOURCE}:{source_product_id}",
        "source": SOURCE,
        "source_product_id": source_product_id,
        "source_uid": source_product_id,
        "source_url": source_url,
        "category_id": category_id,
        "category": category_name,
        "product_name": name,
        "normalized_name": normalize_product_name(name, attrs),
        "description": clean_text(product.get("descriptionPlain") or product.get("descriptionFull"))[:2000],
        "price": product.get("price") or listing_product.get("price") or "",
        "old_price": product.get("priceOriginal") or listing_product.get("priceOriginal") or "",
        "currency": product.get("priceCurrency") or listing_product.get("priceCurrency") or "KZT",
        "availability": ((product.get("catalogPresence") or {}).get("title") if isinstance(product.get("catalogPresence"), dict) else "")
        or ((product.get("presence") or {}).get("presence") if isinstance(product.get("presence"), dict) else ""),
        "city": ((product.get("company") or {}).get("regionName") if isinstance(product.get("company"), dict) else "")
        or ((listing_product.get("company") or {}).get("regionName") if isinstance(listing_product.get("company"), dict) else ""),
        "parsed_at": parsed_at,
        "image_urls": collect_images(product) or collect_images(listing_product),
    }
    row.update(attrs)
    return row


def category_url(alias: str, page: int) -> str:
    base = f"{WEB_HOST}/{alias}"
    if page <= 1:
        return base
    return f"{base}?page={page}"


def iter_listing_products(
    client: SatuBrowserClient,
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
            except (SatuParseError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                if attempt >= retries:
                    raise SatuParseError(f"GET listing {url} failed after {retries} attempts: {exc}") from exc
                time.sleep(retry_sleep * attempt)
        cache = extract_apollo_state(page_html)
        page = find_listing_page(cache)
        products = page.get("products") or []
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
    client: SatuBrowserClient,
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
        except (SatuParseError, urllib.error.URLError, TimeoutError) as exc:
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


def flat_product_fieldnames() -> list[str]:
    return [
        "sku_id",
        "source",
        "source_product_id",
        "source_uid",
        "source_url",
        "category_id",
        "category",
        "product_name",
        "normalized_name",
        "description",
        "price",
        "old_price",
        "currency",
        "availability",
        "city",
        "parsed_at",
        "image_urls",
    ] + flat_attribute_names()


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
    write_csv(out_dir / "satu_products.csv", state.flat_products, flat_product_fieldnames())
    summary = {
        "source": SOURCE,
        "started_at": started_at,
        "finished_at": finished_at,
        "raw_products": raw_count,
        "unique_source_products": len(state.seen_source_products),
        "flat_products": len(state.flat_products),
        "detail_errors": detail_errors,
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
    parser.add_argument("--max-products", type=int, default=100, help="0 means unlimited.")
    parser.add_argument("--max-products-per-category", type=int, default=0, help="0 means use --max-products as total limit.")
    parser.add_argument("--max-pages", type=int, default=3, help="Maximum listing pages per category.")
    parser.add_argument("--page-size", type=int, default=48, help="Expected Satu listing page size.")
    parser.add_argument("--output-dir", default="data/satu")
    parser.add_argument("--headful", action="store_true", help="Show browser window.")
    parser.add_argument("--humanize", action="store_true", help="Enable CloakBrowser human-like input patches.")
    parser.add_argument("--slow-mo-ms", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.5, help="Pause between listing/detail requests.")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-sleep", type=float, default=2.0)
    parser.add_argument("--skip-details", action="store_true", help="Only parse listing data; faster but fewer attrs.")
    parser.add_argument(
        "--direct-http",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use direct HTTP instead of CloakBrowser. Enabled by default for Airflow stability.",
    )
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

    try:
        with SatuBrowserClient(
            headless=not args.headful,
            slow_mo_ms=args.slow_mo_ms,
            humanize=args.humanize,
            direct_http=args.direct_http,
        ) as client, raw_path.open("w", encoding="utf-8") as raw_file:
            for category_key in requested_categories:
                category_flat_count = 0
                for listing_product in iter_listing_products(
                    client,
                    category_key=category_key,
                    page_size_hint=args.page_size,
                    max_pages=args.max_pages,
                    sleep_seconds=args.sleep,
                    retries=args.retries,
                    retry_sleep=args.retry_sleep,
                ):
                    source_product_id = str(listing_product.get("id") or "")
                    if not source_product_id or source_product_id in state.seen_source_products:
                        continue
                    state.seen_source_products.add(source_product_id)
                    raw_count += 1
                    raw_file.write(json.dumps({"category_key": category_key, "listing": listing_product}, ensure_ascii=False) + "\n")

                    detail_product = None
                    detail_cache = None
                    if not args.skip_details:
                        detail_product, detail_cache, detail_error = enrich_detail(
                            client,
                            listing_product,
                            retries=args.retries,
                            retry_sleep=args.retry_sleep,
                        )
                        if detail_error:
                            detail_errors += 1
                            raw_file.write(
                                json.dumps(
                                    {
                                        "category_key": category_key,
                                        "source_product_id": source_product_id,
                                        "detail_error": detail_error,
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                        time.sleep(args.sleep)

                    row = build_flat_product(
                        listing_product,
                        detail_product,
                        detail_cache,
                        category_key,
                        parsed_at=started_at,
                    )
                    state.flat_products.append(row)
                    category_flat_count += 1
                    if len(state.flat_products) % 25 == 0:
                        print(f"parsed {len(state.flat_products)} products")
                    if args.max_products_per_category and category_flat_count >= args.max_products_per_category:
                        break
                    if args.max_products and len(state.flat_products) >= args.max_products:
                        completed = True
                        return 0
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


if __name__ == "__main__":
    raise SystemExit(main())
