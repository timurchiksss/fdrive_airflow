#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скраппер almatyres.kz по sitemap.

Правила обхода:
  - навигация только через sitemap.xml и вложенные sitemap;
  - URL с query-параметрами не используются;
  - sort=, cat_id=, bb*, bms*, bss* заблокированы явно;
  - корзина, кабинет, админка, соцавторизация, контакты/формы и служебные URL
    не скачиваются;
  - товары, каталог и цены сохраняются.

Запуск:
  python3 tale.py
  python3 tale.py --max-products 20
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://almatyres.kz"
SITEMAP_URL = "https://almatyres.kz/sitemap.xml"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

FORBIDDEN_PATH_PARTS = (
    "account",
    "admin",
    "cabinet",
    "contact_now",
    "context/",
    "error/",
    "feedback/",
    "js_i18n",
    "map/frame_map",
    "opinions/create",
    "redirect",
    "preview",
    "site_search",
    "shopping_cart",
    "shop_settings/",
    "social_auth/",
    "tracker/",
    "remote",
    "contacts",
    "contact",
)
FORBIDDEN_QUERY_KEYS = ("sort", "cat_id", "search_term", "sub_domain", "view_as")
FORBIDDEN_QUERY_PREFIXES = ("bb", "bms", "bss")


def is_allowed_url(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    if parts.netloc.lower() not in ("almatyres.kz", "www.almatyres.kz"):
        return False

    path = parts.path.lower()
    if any(bad in path for bad in FORBIDDEN_PATH_PARTS):
        return False

    if parts.query:
        keys = [part.split("=", 1)[0].lower() for part in parts.query.split("&") if part]
        if keys:
            return False
        for key in keys:
            if key in FORBIDDEN_QUERY_KEYS:
                return False
            if any(key.startswith(prefix) for prefix in FORBIDDEN_QUERY_PREFIXES):
                return False

    return True


def request(session: requests.Session, url: str, timeout: int = 30) -> requests.Response:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response


def parse_sitemap_xml(content: bytes) -> tuple[list[str], list[str]]:
    root = ET.fromstring(content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    sitemap_urls = [node.text.strip() for node in root.findall(".//sm:sitemap/sm:loc", ns) if node.text]
    page_urls = [node.text.strip() for node in root.findall(".//sm:url/sm:loc", ns) if node.text]

    if not sitemap_urls and not page_urls:
        sitemap_urls = [node.text.strip() for node in root.findall(".//sitemap/loc") if node.text]
        page_urls = [node.text.strip() for node in root.findall(".//url/loc") if node.text]

    return sitemap_urls, page_urls


def read_sitemap_urls(session: requests.Session, sitemap_url: str, delay: float) -> list[str]:
    seen_sitemaps: set[str] = set()
    page_urls: list[str] = []

    def walk(url: str) -> None:
        if url in seen_sitemaps:
            return
        seen_sitemaps.add(url)
        print(f"Sitemap: {url}")

        response = request(session, url)
        nested, pages = parse_sitemap_xml(response.content)

        for page_url in pages:
            if is_allowed_url(page_url):
                page_urls.append(page_url)

        for nested_url in nested:
            if is_allowed_url(nested_url):
                time.sleep(delay)
                walk(nested_url)

    walk(sitemap_url)
    return list(dict.fromkeys(page_urls))


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def clean_price(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        return str(int(float(value)))

    text = str(value).strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        return str(int(float(text.replace(",", "."))))
    return re.sub(r"[^\d]", "", text)


def load_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            items.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict):
            graph = data.get("@graph")
            if isinstance(graph, list):
                items.extend(x for x in graph if isinstance(x, dict))
            items.append(data)
    return items


def find_ld(items: list[dict[str, Any]], ld_type: str) -> dict[str, Any]:
    for item in items:
        item_type = item.get("@type")
        if item_type == ld_type or (isinstance(item_type, list) and ld_type in item_type):
            return item
    return {}


def extract_breadcrumbs(ld_breadcrumbs: dict[str, Any]) -> str:
    result = []
    for item in ld_breadcrumbs.get("itemListElement") or []:
        node = item.get("item") or {}
        name = node.get("name") if isinstance(node, dict) else ""
        if name:
            result.append(str(name))
    return " > ".join(result)


def extract_specs(soup: BeautifulSoup) -> dict[str, str]:
    specs: dict[str, str] = {}
    for row in soup.select("table.b-product-info tr"):
        cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.select("td")]
        if len(cells) >= 2 and cells[0] and cells[1] and cells[0] != cells[1]:
            specs[cells[0]] = cells[1]
    return specs


def extract_images(soup: BeautifulSoup, product_ld: dict[str, Any]) -> list[str]:
    images: list[str] = []
    ld_image = product_ld.get("image")
    if isinstance(ld_image, str):
        images.append(ld_image)
    elif isinstance(ld_image, list):
        images.extend(str(x) for x in ld_image if x)

    for img in soup.select(".cs-product img, .cs-product-gallery img, img.cs-image-holder__image"):
        src = img.get("data-src") or img.get("src")
        if src:
            images.append(urljoin(BASE_URL, src))

    return list(dict.fromkeys(images))


def extract_product(session: requests.Session, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(request(session, url).text, "html.parser")
    ld_items = load_json_ld(soup)
    product_ld = find_ld(ld_items, "Product")
    breadcrumb_ld = find_ld(ld_items, "BreadcrumbList")

    offers = product_ld.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}

    name = clean_text(product_ld.get("name")) or clean_text(soup.select_one("h1").get_text(" ", strip=True) if soup.select_one("h1") else "")
    price = clean_price(offers.get("price") or clean_text(soup.select_one(".b-product-cost__price").get_text(" ", strip=True) if soup.select_one(".b-product-cost__price") else ""))
    availability_raw = str(offers.get("availability") or clean_text(soup.select_one(".b-product-data__item_type_available, .cs-sticky-panel__product-status").get_text(" ", strip=True) if soup.select_one(".b-product-data__item_type_available, .cs-sticky-panel__product-status") else ""))

    row: dict[str, Any] = {
        "url": url,
        "product_id": (re.search(r"/p(\d+)-", url) or ["", ""])[1],
        "name": name,
        "price": price,
        "currency": offers.get("priceCurrency") or "KZT" if price else "",
        "availability": availability_raw.replace("http://schema.org/", "").replace("https://schema.org/", ""),
        "category": extract_breadcrumbs(breadcrumb_ld),
        "description": clean_text(product_ld.get("description")),
        "images": " | ".join(extract_images(soup, product_ld)),
        "title": clean_text(soup.title.get_text(" ", strip=True) if soup.title else ""),
    }
    row.update(extract_specs(soup))
    return row


def extract_category(session: requests.Session, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(request(session, url).text, "html.parser")
    ld_items = load_json_ld(soup)
    products = [item for item in ld_items if item.get("@type") == "Product"]
    return {
        "url": url,
        "category_id": (re.search(r"/g(\d+)-", url) or ["", ""])[1],
        "name": clean_text(soup.select_one("h1").get_text(" ", strip=True) if soup.select_one("h1") else ""),
        "title": clean_text(soup.title.get_text(" ", strip=True) if soup.title else ""),
        "products_on_page": len(products),
    }


def save_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return

    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def save_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Скраппер almatyres.kz только по sitemap.")
    parser.add_argument("--sitemap", default=SITEMAP_URL)
    parser.add_argument("--out-products", default="almatyres_products.csv")
    parser.add_argument("--out-products-jsonl", default="almatyres_products.jsonl")
    parser.add_argument("--out-categories", default="almatyres_categories.csv")
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--max-products", type=int, default=0)
    parser.add_argument("--max-categories", type=int, default=0)
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }
    )

    sitemap_urls = read_sitemap_urls(session, args.sitemap, args.delay)
    product_urls = [url for url in sitemap_urls if re.search(r"/p\d+.*\.html$", url)]
    category_urls = [url for url in sitemap_urls if re.search(r"/g\d+-", url)]

    if args.max_products:
        product_urls = product_urls[: args.max_products]
    if args.max_categories:
        category_urls = category_urls[: args.max_categories]

    print(f"Товаров в sitemap после фильтра: {len(product_urls)}")
    print(f"Категорий в sitemap после фильтра: {len(category_urls)}")

    categories: list[dict[str, Any]] = []
    for index, url in enumerate(category_urls, 1):
        try:
            print(f"Категория {index}/{len(category_urls)}: {url}")
            categories.append(extract_category(session, url))
        except Exception as exc:
            print(f"Ошибка категории {url}: {exc}", file=sys.stderr)
        time.sleep(args.delay)

    products: list[dict[str, Any]] = []
    for index, url in enumerate(product_urls, 1):
        try:
            print(f"Товар {index}/{len(product_urls)}: {url}")
            products.append(extract_product(session, url))
        except Exception as exc:
            print(f"Ошибка товара {url}: {exc}", file=sys.stderr)
        time.sleep(args.delay)

    save_csv(categories, Path(args.out_categories))
    save_csv(products, Path(args.out_products))
    save_jsonl(products, Path(args.out_products_jsonl))

    print(f"Готово: категорий {len(categories)}, товаров {len(products)}")
    print(f"Категории CSV: {Path(args.out_categories).resolve()}")
    print(f"Товары CSV:    {Path(args.out_products).resolve()}")
    print(f"Товары JSONL:  {Path(args.out_products_jsonl).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
