from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_API = "https://api.f7.kz/api/newcatalog"
BASE_SITE = "https://f7.kz"

CATEGORIES = [
    "tyres",
    "trucks",
    "wheels",
    "otr"
]

# ----------------------------
# Session + Retry
# ----------------------------

session = requests.Session()

retry = Retry(
    total=5,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504]
)

adapter = HTTPAdapter(max_retries=retry)

session.mount("http://", adapter)
session.mount("https://", adapter)

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://f7.kz",
    "Referer": "https://f7.kz/"
})


# ----------------------------
# Save to CSV immediately
# ----------------------------

def save_rows(rows, filename: Path):
    if not rows:
        return

    df = pd.DataFrame(rows)

    filename.parent.mkdir(parents=True, exist_ok=True)
    file_exists = filename.exists()

    df.to_csv(
        filename,
        mode="a",
        header=not file_exists,
        index=False,
        encoding="utf-8-sig"
    )


# ----------------------------
# Stocks
# ----------------------------

def parse_stocks(product):
    stocks = product.get("stocks", [])

    if not stocks:
        return None

    return " | ".join(
        f"{stock.get('storage_name', '')} - {stock.get('quantity', 0)} шт."
        for stock in stocks
        if isinstance(stock, dict)
    )


# ----------------------------
# Product URL
# ----------------------------

def get_product_url(product, category):
    category_slug = product.get("category_slug") or category
    updated_slug = product.get("updated_slug")

    return f"{BASE_SITE}/{category_slug}/{updated_slug}"


# ----------------------------
# Card Features
# ----------------------------

def parse_features_from_card(url):

    try:
        response = session.get(url, timeout=30)

        if response.status_code != 200:
            return {}

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        features = {}

        for feature in soup.select(".feature"):

            key = feature.select_one(".sub")
            value = feature.select_one(".value")

            if not key or not value:
                continue

            key_text = key.get_text(strip=True)
            value_text = value.get_text(strip=True)

            if key_text and value_text:
                features[key_text] = value_text

        return features

    except Exception as e:

        print("CARD ERROR:", url)
        print(e)

        return {}


# ----------------------------
# First image
# ----------------------------

def get_first_image(product):

    images = product.get("images")

    if isinstance(images, list) and images:
        return images[0]

    return None


# ----------------------------
def parse_category(
    category: str,
    output_dir: Path,
    delay: float = 0.5,
    max_products: int = 0,
    with_card_features: bool = False,
    card_delay: float = 0.0,
) -> Path:
    filename = output_dir / f"f7_{category}.csv"

    if filename.exists():
        filename.unlink()

    page = 1
    total_saved = 0

    while True:
        if max_products and total_saved >= max_products:
            print(f"{category}: reached max products limit: {max_products}")
            break

        api_url = (
            f"{BASE_API}/{category}/products"
            f"?city=almaty&sorting=new&page={page}"
        )

        print("\n", api_url)

        try:
            response = session.post(api_url, json={}, timeout=30)
        except Exception as e:
            print("API ERROR:", e)
            print("Waiting 30 sec...")
            time.sleep(30)
            continue

        if response.status_code != 200:
            print("STATUS:", response.status_code)
            print(response.text[:500])
            break

        try:
            data = response.json()
        except Exception:
            print("JSON ERROR")
            print(response.text[:500])
            break

        products = data.get("products", {}).get("data", [])

        if not products:
            break

        rows = []

        for product in products:
            if max_products and total_saved + len(rows) >= max_products:
                break
            product_url = get_product_url(product, category)

            row = {
                "id": product.get("id"),
                "title": product.get("title"),
                "full_title": product.get("full_title"),
                "internet_title": product.get("internet_title"),
                "category": product.get("category_slug") or category,
                "type": product.get("type"),
                "price": product.get("price"),
                "sku": product.get("sku"),
                "code": product.get("code"),
                "guid": product.get("guid"),
                "image": get_first_image(product),
                "url": product_url,
                "stocks": parse_stocks(product),
                "created_at": product.get("created_at"),
                "updated_at": product.get("updated_at"),
            }

            if with_card_features:
                try:
                    features = parse_features_from_card(product_url)
                    row.update(features)
                except Exception as e:
                    print("FEATURE ERROR")
                    print(product_url)
                    print(e)

            rows.append(row)
            if with_card_features and card_delay > 0:
                time.sleep(card_delay)

        save_rows(rows, filename)
        total_saved += len(rows)

        meta = data.get("products", {}).get("meta", {})
        last_page = meta.get("last_page", page)

        print(f"{category}: page {page}/{last_page}, saved {len(rows)} rows, total {total_saved}")

        if page >= last_page or (max_products and total_saved >= max_products):
            break

        page += 1
        time.sleep(delay)

    print(f"\nFINISHED CATEGORY: {category}")
    return filename


def run(
    output_dir: str | Path = "data/f7",
    categories: list[str] | None = None,
    delay: float = 0.5,
    max_products: int = 0,
    with_card_features: bool = False,
    card_delay: float = 0.0,
) -> list[Path]:
    output_path = Path(output_dir)
    selected_categories = categories or CATEGORIES
    return [
        parse_category(
            category,
            output_path,
            delay=delay,
            max_products=max_products,
            with_card_features=with_card_features,
            card_delay=card_delay,
        )
        for category in selected_categories
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse f7.kz catalog categories.")
    parser.add_argument("--output-dir", default="data/f7")
    parser.add_argument("--categories", default=",".join(CATEGORIES))
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--max-products", type=int, default=0, help="Max products per category. 0 means unlimited.")
    parser.add_argument(
        "--with-card-features",
        action="store_true",
        help="Also open every product card and merge HTML features. This is much slower.",
    )
    parser.add_argument("--card-delay", type=float, default=0.0, help="Delay between product card requests.")
    args = parser.parse_args()

    categories = [item.strip() for item in args.categories.split(",") if item.strip()]
    unknown = [category for category in categories if category not in CATEGORIES]
    if unknown:
        raise SystemExit(f"Unknown categories: {', '.join(unknown)}")

    run(
        args.output_dir,
        categories=categories,
        delay=args.delay,
        max_products=args.max_products,
        with_card_features=args.with_card_features,
        card_delay=args.card_delay,
    )
    print("\nDONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
