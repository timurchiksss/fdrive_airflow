#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скраппер FDrive для категорий вида:
https://fdrive.kz/almaty/c/masla-i-zhidkosti/f

Что сохраняет:
  1. CSV с основными полями и всеми характеристиками товара.
  2. JSONL с сырым объектом товара из __NEXT_DATA__, чтобы не терять данные.

Запуск:
  python3 scrap.py
  python3 scrap.py "https://fdrive.kz/almaty/c/masla-i-zhidkosti/f" --out fdrive_masla.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


DEFAULT_URL = "https://fdrive.kz/almaty/c/masla-i-zhidkosti/f"
BASE_URL = "https://fdrive.kz"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class ListingPage:
    page: int
    total_count: int
    products: list[dict[str, Any]]
    category_name: str
    raw_listing_data: dict[str, Any]


def build_page_url(start_url: str, page: int) -> str:
    start_url = start_url.rstrip("/")
    if page <= 1:
        return start_url
    return f"{start_url}/page/{page}"


def build_tyres_page_url(start_url: str, page: int) -> str:
    start_url = start_url.rstrip("/")
    if page <= 1:
        return start_url
    return f"{start_url}/page{page}"


def fetch_next_data(session: requests.Session, url: str, timeout: int = 30) -> dict[str, Any]:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    script = soup.select_one("#__NEXT_DATA__")
    if not script or not script.string:
        raise RuntimeError(f"Не найден __NEXT_DATA__ на странице: {url}")

    return json.loads(script.string)


def parse_listing_page(next_data: dict[str, Any]) -> ListingPage:
    page_props = next_data.get("props", {}).get("pageProps", {})
    listing_data = page_props.get("listingData") or {}
    result = listing_data.get("result") or {}
    products = result.get("listing") or []
    category = result.get("category") or {}

    return ListingPage(
        page=int(listing_data.get("page") or 1),
        total_count=int(listing_data.get("count") or len(products)),
        products=products,
        category_name=category.get("name") or "",
        raw_listing_data=listing_data,
    )


def product_url(product: dict[str, Any]) -> str:
    slug = product.get("slug") or ""
    if not slug:
        return ""
    return f"{BASE_URL}/p/{slug}"


def images(product: dict[str, Any]) -> list[str]:
    result = []
    for item in product.get("media") or []:
        image_path = item.get("image_path") or item.get("url") or item.get("src")
        if image_path:
            result.append(image_path)
    return result


def tyre_images(product: dict[str, Any]) -> list[str]:
    result = []
    if product.get("imageUrl"):
        result.append(product["imageUrl"])
    for item in product.get("medias") or []:
        image_url = item.get("url") or item.get("image_path") or item.get("src")
        if image_url:
            result.append(image_url)
    return list(dict.fromkeys(result))


def attr_map(product: dict[str, Any]) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for attr in product.get("attributes") or []:
        name = str(attr.get("name") or attr.get("code") or "").strip()
        value = str(attr.get("value_name") or attr.get("value") or "").strip()
        if name and value:
            attrs[name] = value
    return attrs


def flatten_product(product: dict[str, Any], fallback_category: str) -> dict[str, Any]:
    info = as_dict(product.get("info"))
    cost = as_dict(product.get("cost_info"))
    categories = as_list(product.get("categories"))
    category_names = [as_dict(c).get("name") for c in categories if as_dict(c).get("name")]

    row: dict[str, Any] = {
        "product_id": product.get("productId") or product.get("id") or "",
        "name": info.get("title") or product.get("name") or "",
        "price": cost.get("price") or "",
        "price_old": cost.get("price_old") or "",
        "url": product_url(product),
        "slug": product.get("slug") or "",
        "category": " | ".join(category_names) or fallback_category,
        "brand_code": info.get("brand_code") or "",
        "brand": info.get("brand") or "",
        "brand_name": info.get("brand_name") or "",
        "images": " | ".join(images(product)),
        "listing_page": product.get("_listing_page") or "",
        "listing_index": product.get("_listing_index") or "",
        "is_duplicate": product.get("_is_duplicate") or "",
    }

    for key, value in attr_map(product).items():
        row[key] = value

    return row


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def flatten_tyre(product: dict[str, Any]) -> dict[str, Any]:
    product_type_raw = product.get("productType")
    product_type = as_dict(product_type_raw)
    product_type_text = product_type_raw if isinstance(product_type_raw, str) else ""
    tyre_stud_type = as_dict(product.get("tyreStudType"))
    promotions = as_list(product.get("promotions"))

    return {
        "product_id": product.get("id") or "",
        "name": product.get("name") or "",
        "price": product.get("price") or "",
        "price_with_discount": product.get("priceWithDiscount") or "",
        "price_without_discount": product.get("priceWithoutDiscount") or "",
        "url": f"{BASE_URL}/tyre/{product.get('slug')}" if product.get("slug") else "",
        "slug": product.get("slug") or "",
        "category": product_type.get("title") or product_type_text or "Шины",
        "product_type": product_type.get("name") or product_type_text or "",
        "brand": product.get("brand") or "",
        "brand_slug": product.get("brandSlug") or "",
        "season": product.get("season") or "",
        "size": product.get("sizeStr") or "",
        "width": product.get("width") or "",
        "height": product.get("height") or "",
        "diameter": product.get("diameter") or "",
        "weight_single_index": product.get("weightSingleIndex") or "",
        "weight_double_index": product.get("weightDoubleIndex") or "",
        "velocity_index": product.get("velocityIndex") or "",
        "manufacture_country": product.get("manufactureCountryCachedName") or "",
        "quantity_available": product.get("quantityAvailibleTotal") or "",
        "quantity_available_text": product.get("quantityAvailibleTotalStr") or "",
        "cashback": product.get("cashback") or "",
        "tyre_auto_type_id": product.get("tyreAutoTypeId") or "",
        "tyre_auto_type_name": product.get("tyreAutoTypeName") or "",
        "tyre_stud_type_id": tyre_stud_type.get("id") or "",
        "tyre_stud_type_name": tyre_stud_type.get("name") or "",
        "rating": product.get("rating") or "",
        "votes": product.get("votes") or "",
        "is_ecar": product.get("isEcar"),
        "is_freedom_tyre": product.get("isFreedomTyre"),
        "is_freedom_tyre_promotion": product.get("isFreedomTyrePromotion"),
        "freedom_tyre_promotion_percent": product.get("freedomTyrePromotionPercent") or "",
        "promotions": " | ".join(str(item) for item in promotions),
        "images": " | ".join(tyre_images(product)),
        "listing_page": product.get("_listing_page") or "",
        "listing_index": product.get("_listing_index") or "",
        "is_duplicate": product.get("_is_duplicate") or "",
    }


def safe_output_name(start_url: str) -> str:
    path = urlparse(start_url).path.strip("/")
    slug = re.sub(r"[^a-zA-Z0-9а-яА-Я_-]+", "_", path).strip("_")
    return f"{slug or 'fdrive'}_products.csv"


def save_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        raise RuntimeError("Нет данных для сохранения CSV.")

    columns: list[str] = []
    preferred = [
        "product_id",
        "name",
        "price",
        "price_old",
        "url",
        "slug",
        "category",
        "brand_code",
        "brand",
        "brand_name",
        "images",
        "listing_page",
        "listing_index",
        "is_duplicate",
    ]
    for col in preferred:
        if any(col in row for row in rows):
            columns.append(col)
    for row in rows:
        for col in row:
            if col not in columns:
                columns.append(col)

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def save_jsonl(products: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as file:
        for product in products:
            file.write(json.dumps(product, ensure_ascii=False) + "\n")


def scrape_category(
    start_url: str,
    delay: float,
    dedupe: bool = False,
    max_products: int = 0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Referer": BASE_URL,
        }
    )

    first_url = build_page_url(start_url, 1)
    print(f"Загружаю страницу 1: {first_url}")
    first_page = parse_listing_page(fetch_next_data(session, first_url))

    if not first_page.products:
        return [], []

    page_size = len(first_page.products)
    total_pages = max(1, math.ceil(first_page.total_count / page_size))
    print(
        f"Категория: {first_page.category_name or 'без названия'}; "
        f"товаров: {first_page.total_count}; страниц: {total_pages}"
    )

    raw_products: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_products(products: list[dict[str, Any]], page: int) -> int:
        added = 0
        for index, product in enumerate(products, 1):
            if max_products and len(raw_products) >= max_products:
                break
            key = str(product.get("productId") or product.get("slug") or "")
            is_duplicate = bool(key and key in seen)
            if dedupe and is_duplicate:
                continue
            product = dict(product)
            product["_listing_page"] = page
            product["_listing_index"] = index
            product["_is_duplicate"] = "yes" if is_duplicate else ""
            if key:
                seen.add(key)
            raw_products.append(product)
            added += 1
        return added

    added = add_products(first_page.products, 1)
    print(f"Страница 1: +{added}, всего {len(raw_products)}")

    for page in range(2, total_pages + 1):
        if max_products and len(raw_products) >= max_products:
            print(f"Достигнут лимит товаров: {max_products}")
            break
        url = build_page_url(start_url, page)
        time.sleep(delay)
        print(f"Загружаю страницу {page}: {url}")
        listing_page = parse_listing_page(fetch_next_data(session, url))
        added = add_products(listing_page.products, page)
        print(f"Страница {page}: +{added}, всего {len(raw_products)}")

    rows = [flatten_product(product, first_page.category_name) for product in raw_products]
    return rows, raw_products


def scrape_tyres(
    start_url: str,
    delay: float,
    dedupe: bool = False,
    max_pages: int = 0,
    max_products: int = 0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Referer": BASE_URL,
        }
    )

    print(f"Загружаю страницу 1: {start_url}")
    next_data = fetch_next_data(session, build_tyres_page_url(start_url, 1))
    listing = next_data.get("props", {}).get("pageProps", {}).get("listingResults") or {}
    first_products = listing.get("results") or []
    if not first_products:
        return [], []

    page_size = int(listing.get("pageSize") or len(first_products))
    total_items = int(listing.get("totalItems") or len(first_products))
    total_pages = max(1, math.ceil(total_items / page_size))
    if max_pages:
        total_pages = min(total_pages, max_pages)

    print(f"Шины: товаров: {total_items}; страниц: {total_pages}; на странице: {page_size}")

    raw_products: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_products(products: list[dict[str, Any]], page: int) -> int:
        added = 0
        for index, product in enumerate(products, 1):
            if max_products and len(raw_products) >= max_products:
                break
            key = str(product.get("id") or product.get("slug") or "")
            is_duplicate = bool(key and key in seen)
            if dedupe and is_duplicate:
                continue
            product = dict(product)
            product["_listing_page"] = page
            product["_listing_index"] = index
            product["_is_duplicate"] = "yes" if is_duplicate else ""
            if key:
                seen.add(key)
            raw_products.append(product)
            added += 1
        return added

    added = add_products(first_products, 1)
    print(f"Страница 1: +{added}, всего {len(raw_products)}")

    for page in range(2, total_pages + 1):
        if max_products and len(raw_products) >= max_products:
            print(f"Достигнут лимит товаров: {max_products}")
            break
        url = build_tyres_page_url(start_url, page)
        time.sleep(delay)
        print(f"Загружаю страницу {page}: {url}")
        next_data = fetch_next_data(session, url)
        listing = next_data.get("props", {}).get("pageProps", {}).get("listingResults") or {}
        products = listing.get("results") or []
        added = add_products(products, page)
        print(f"Страница {page}: +{added}, всего {len(raw_products)}")

    rows = [flatten_tyre(product) for product in raw_products]
    return rows, raw_products


def main() -> int:
    parser = argparse.ArgumentParser(description="Скраппер товаров FDrive из Next.js JSON.")
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="URL категории FDrive")
    parser.add_argument("--out", default="", help="Путь для CSV. По умолчанию имя строится из URL.")
    parser.add_argument("--jsonl", default="", help="Путь для сырого JSONL. По умолчанию рядом с CSV.")
    parser.add_argument("--delay", type=float, default=0.5, help="Пауза между страницами в секундах.")
    parser.add_argument("--dedupe", action="store_true", help="Удалять повторы по productId/slug.")
    parser.add_argument("--max-pages", type=int, default=0, help="Ограничить число страниц для теста.")
    parser.add_argument("--max-products", type=int, default=0, help="Ограничить число товаров. 0 значит без лимита.")
    args = parser.parse_args()

    csv_path = Path(args.out or safe_output_name(args.url))
    jsonl_path = Path(args.jsonl or csv_path.with_suffix(".jsonl"))

    if "/tyres/" in args.url:
        rows, raw_products = scrape_tyres(
            args.url,
            args.delay,
            dedupe=args.dedupe,
            max_pages=args.max_pages,
            max_products=args.max_products,
        )
    else:
        rows, raw_products = scrape_category(
            args.url,
            args.delay,
            dedupe=args.dedupe,
            max_products=args.max_products,
        )
    if not rows:
        print("Товары не найдены.", file=sys.stderr)
        return 1

    save_csv(rows, csv_path)
    save_jsonl(raw_products, jsonl_path)

    print(f"Готово: {len(rows)} товаров")
    print(f"CSV:   {csv_path.resolve()}")
    print(f"JSONL: {jsonl_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
