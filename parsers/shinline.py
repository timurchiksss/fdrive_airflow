import argparse
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_URL = "https://shinline.kz"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CATEGORIES = {
    "legkovye_shiny": "https://shinline.kz/catalog/legkovye_shiny/",
    "gruzovye_shiny": "https://shinline.kz/catalog/gruzovye_shiny/",
    "legkogruzovye_shiny": "https://shinline.kz/catalog/legkogruzovye_shiny/",
    "selkhoz_shiny": "https://shinline.kz/catalog/selkhoz_shiny/",
    "industrial_shiny": "https://shinline.kz/catalog/industrial_shiny/",
    "wheels": "https://shinline.kz/catalog/wheels/",
}

_thread_local = threading.local()


def get_session():
    session = getattr(_thread_local, "session", None)
    if session is not None:
        return session

    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(HEADERS)
    _thread_local.session = session
    return session


def clean_text(text):
    if not text:
        return None
    text = text.replace("\u200b", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_model_info(text):
    if not text:
        return None

    remove_phrases = [
        "Размеры модели Посмотреть все размеры модели",
        "Размеры модели",
        "Посмотреть все размеры модели",
    ]

    for phrase in remove_phrases:
        text = text.replace(phrase, "")

    return clean_text(text)


def get_soup(url):
    try:
        response = get_session().get(url, timeout=30)
        response.encoding = "utf-8"
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"ERROR URL: {url}")
        print(e)
        return None


def parse_warehouses(soup):
    warehouses = []

    blocks = soup.select(".card-info_availability")

    for block in blocks:
        style = block.get("style", "")

        if "display: none" in style:
            continue

        title = block.select_one(".card-info_availability-title")
        stock = block.select_one(".card-main_info-stock")

        if not title or not stock:
            continue

        warehouse_name = clean_text(title.get_text(" ", strip=True))
        stock_text = clean_text(stock.get_text(" ", strip=True))

        if not warehouse_name or not stock_text:
            continue

        stock_text = stock_text.replace("В наличии:", "").strip()

        if "Нет в наличии" not in stock_text:
            warehouses.append(f"{warehouse_name}: {stock_text}")

    return " | ".join(warehouses) if warehouses else None


def parse_product(url):
    soup = get_soup(url)

    if soup is None:
        return None

    product = {}
    product["url"] = url

    title = soup.find("h1")
    product["name"] = clean_text(title.get_text(" ", strip=True)) if title else None

    price = soup.select_one('[data-currency="KZT"][data-value]')
    product["price"] = price.get("data-value") if price else None

    article = soup.select_one(".card-main_code .value")
    product["article"] = clean_text(article.get_text(" ", strip=True)) if article else None

    product["warehouses_stock"] = parse_warehouses(soup)

    desc_block = soup.select_one("#cardDescription .description_detail")
    product["description"] = clean_text(desc_block.get_text(" ", strip=True)) if desc_block else None

    model_block = soup.select_one("#cardModel")
    product["model_info"] = clean_model_info(model_block.get_text(" ", strip=True)) if model_block else None

    rows = soup.select(".card-info_description-row")

    for row in rows:
        key = row.select_one(".card-info_description-key")
        value = row.select_one(".card-info_description-value")

        if key and value:
            k = clean_text(key.get_text(" ", strip=True))
            v = clean_text(value.get_text(" ", strip=True))

            if k and k != "Run on flat":
                product[k] = v

    return product


def parse_product_safe(product_url):
    try:
        return parse_product(product_url)
    except Exception as e:
        print("PRODUCT ERROR")
        print(product_url)
        print(e)
        return None


def parse_products(product_urls, workers=4, product_delay=0.0):
    if workers <= 1:
        products = []
        for index, product_url in enumerate(product_urls, start=1):
            print(f"PRODUCT {index}: {product_url}")
            product = parse_product_safe(product_url)
            if product:
                products.append(product)
            if product_delay:
                time.sleep(product_delay)
        return products

    products_by_url = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for index, product_url in enumerate(product_urls, start=1):
            print(f"PRODUCT {index}: {product_url}")
            futures[executor.submit(parse_product_safe, product_url)] = product_url
            if product_delay:
                time.sleep(product_delay)

        for future in as_completed(futures):
            product_url = futures[future]
            product = future.result()
            if product:
                products_by_url[product_url] = product

    return [products_by_url[url] for url in product_urls if url in products_by_url]


def save_progress(products, filename):
    df = pd.DataFrame(products)

    columns_to_drop = [
        "availability",
        "seo_title",
        "seo_description",
        "how_to_buy",
        "model_sizes_info",
        "raw_attributes",
        "Run on flat",
    ]

    df = df.drop(columns=[col for col in columns_to_drop if col in df.columns])

    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(filename, index=False, encoding="utf-8-sig")


def process_category(
    category_name,
    category_url,
    output_dir="data/shinline",
    max_products=0,
    workers=4,
    product_delay=0.0,
    page_delay=0.2,
):
    print("\n" + "=" * 60)
    print(category_name)
    print("=" * 60)

    products = []
    seen_links = set()
    page = 1
    filename = Path(output_dir) / f"{category_name}.csv"

    while True:
        page_url = f"{category_url}?PAGEN_1={page}"
        print(f"\nPAGE {page}")

        soup = get_soup(page_url)

        if soup is None:
            break

        cards = soup.select("a.product-card_title")

        if not cards:
            print("No more products")
            break

        print(f"Found cards on page: {len(cards)}")

        page_product_urls = []

        for card in cards:
            if max_products and len(products) + len(page_product_urls) >= max_products:
                print(f"Reached max products limit for {category_name}: {max_products}")
                break
            href = card.get("href")

            if not href:
                continue

            product_url = urljoin(BASE_URL, href)

            if product_url in seen_links:
                continue

            seen_links.add(product_url)
            page_product_urls.append(product_url)

        if not page_product_urls:
            print("No new products on this page. Category finished.")
            break

        page_products = parse_products(
            page_product_urls,
            workers=workers,
            product_delay=product_delay,
        )
        products.extend(page_products)

        if max_products and len(products) >= max_products:
            print(f"Category limit reached. Category finished: {category_name}")
            break

        save_progress(products, filename)
        print(f"SAVED PROGRESS: {len(products)} products -> {filename}")

        page += 1
        if page_delay:
            time.sleep(page_delay)

    save_progress(products, filename)
    print(f"DONE CATEGORY: {category_name}, total: {len(products)}")
    return filename


def run(
    output_dir="data/shinline",
    categories=None,
    max_products=0,
    workers=4,
    product_delay=0.0,
    page_delay=0.2,
):
    print("START PAGE-BY-PAGE PARSER")

    selected = categories or list(CATEGORIES)
    output_files = []
    for category_name in selected:
        output_files.append(
            process_category(
                category_name,
                CATEGORIES[category_name],
                output_dir=output_dir,
                max_products=max_products,
                workers=workers,
                product_delay=product_delay,
                page_delay=page_delay,
            )
        )

    print("\nDONE")
    return output_files


def main():
    parser = argparse.ArgumentParser(description="Parse shinline.kz product categories.")
    parser.add_argument("--output-dir", default="data/shinline")
    parser.add_argument("--categories", default=",".join(CATEGORIES))
    parser.add_argument("--max-products", type=int, default=0, help="Max products per category. 0 means unlimited.")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent product requests per category.")
    parser.add_argument("--product-delay", type=float, default=0.0, help="Delay between scheduling product requests.")
    parser.add_argument("--page-delay", type=float, default=0.2, help="Delay between catalog pages.")
    args = parser.parse_args()

    categories = [item.strip() for item in args.categories.split(",") if item.strip()]
    unknown = [category for category in categories if category not in CATEGORIES]
    if unknown:
        raise SystemExit(f"Unknown categories: {', '.join(unknown)}")

    run(
        output_dir=args.output_dir,
        categories=categories,
        max_products=args.max_products,
        workers=max(1, args.workers),
        product_delay=max(0.0, args.product_delay),
        page_delay=max(0.0, args.page_delay),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
