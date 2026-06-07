"""Парсер car-city (carcity.kz) — Nuxt SSR + Laravel.

Обход:
  1) category.xml (S3) -> целевые категории (шины/масла/фильтры/АКБ);
  2) листинг категории постранично через ?per_page=N&page=K -> URL товаров;
  3) карточка товара: JSON-LD (@type=Product) -> name/brand/sku/image/offer,
     BreadcrumbList -> категория; атрибуты -> из названия + категории.

Цены/наличие берём из JSON-LD (стабильный структурированный источник).
Модель Product.offers — список, поэтому при появлении мультипродавца его
легко добавить, но сейчас car-city отдаёт в структурных данных одно
активное предложение на товар.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import config
from freedom_parser.common import categories, nuxt
from freedom_parser.common.attributes import (
    attributes_from_carcity_chars,
    carcity_availability,
    carcity_oem_numbers,
    extract_for_group,
    parse_price,
)
from freedom_parser.common.http import Fetcher
from freedom_parser.common.models import Offer, Product


def _availability_from_days(days: int | None) -> str:
    """delivery_days -> наличие: 0 = «В наличии», N>0 = «Под заказ: N дн»."""
    if days is None:
        return "В наличии"
    return "В наличии" if days == 0 else f"Под заказ: {days} дн"

log = logging.getLogger("freedom_parser.carcity")

SOURCE = "carcity"
PER_PAGE = config.CARCITY_PER_PAGE
MAX_PAGES = 400  # предохранитель от бесконечной пагинации

_PRODUCT_HREF_RE = re.compile(r'href="(/product/[a-z0-9\-]+?-\d+)(?:\?[^"]*)?"')
_ID_RE = re.compile(r"-(\d+)$")


def _product_id(path: str) -> str:
    m = _ID_RE.search(path)
    return m.group(1) if m else path.rsplit("/", 1)[-1]


class CarCityScraper:
    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or Fetcher()

    # ---- 1-2. Обнаружение URL товаров ----
    def _target_categories(self, groups: set[str]) -> list[tuple[str, str, str]]:
        """[(category_url, group, slug)] из явного allowlist (config.CARCITY_CATEGORIES)."""
        out: list[tuple[str, str, str]] = []
        for group in ("tires", "oils", "filters", "batteries"):
            if group not in groups:
                continue
            for slug in config.CARCITY_CATEGORIES.get(group, []):
                url = f"{config.CARCITY_BASE}/category/{slug}"
                out.append((url, group, slug))
        return out

    def _product_urls_in_category(self, category_url: str) -> list[str]:
        urls: list[str] = []
        seen_ids: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            url = f"{category_url}?per_page={PER_PAGE}&page={page}"
            resp = self.fetcher.get(url)
            if resp is None:
                break
            paths = _PRODUCT_HREF_RE.findall(resp.text)
            new = 0
            for p in dict.fromkeys(paths):
                pid = _product_id(p)
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)
                urls.append(config.CARCITY_BASE + p)
                new += 1
            if new == 0:
                break
        return urls

    def discover(self, groups: set[str], limit: int | None = None,
                 per_group: int | None = None) -> list[tuple[str, str, str]]:
        """Список (product_url, group_hint, category_slug), уникальный по id товара.

        per_group — ограничить число товаров на КАЖДУЮ группу (для сбалансированной
        выборки при профайлинге); limit — общий потолок.
        """
        from collections import defaultdict
        result: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        group_count: dict[str, int] = defaultdict(int)
        for cat_url, group, slug in self._target_categories(groups):
            if per_group and group_count[group] >= per_group:
                continue
            log.info("car-city: категория %s (%s)", cat_url, group)
            for purl in self._product_urls_in_category(cat_url):
                pid = _product_id(purl)
                if pid in seen:
                    continue
                seen.add(pid)
                result.append((purl, group, slug))
                group_count[group] += 1
                if limit and len(result) >= limit:
                    return result
                if per_group and group_count[group] >= per_group:
                    break
        return result

    # ---- 3. Разбор карточки ----
    @staticmethod
    def _jsonld_nodes(html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        nodes: list[dict] = []
        for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(tag.string or tag.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and "@graph" in data:
                nodes.extend(data["@graph"])
            elif isinstance(data, list):
                nodes.extend(data)
            elif isinstance(data, dict):
                nodes.append(data)
        return nodes

    def parse(self, url: str, group_hint: str = "", category_hint: str = "") -> Product | None:
        resp = self.fetcher.get(url)
        if resp is None:
            return None
        nodes = self._jsonld_nodes(resp.text)
        product_node = next((n for n in nodes if n.get("@type") == "Product"), None)
        breadcrumb = next((n for n in nodes if n.get("@type") == "BreadcrumbList"), None)
        if not product_node:
            log.warning("car-city: нет JSON-LD Product на %s", url)
            return None

        name = product_node.get("name", "").strip()
        brand = ""
        b = product_node.get("brand")
        if isinstance(b, dict):
            brand = b.get("name", "")
        elif isinstance(b, str):
            brand = b
        article = product_node.get("sku", "")
        image = product_node.get("image") or ""
        if isinstance(image, list):
            image = image[0] if image else ""

        # Категория из хлебных крошек: L1 = вторая, leaf = предпоследняя.
        cat_l1 = cat_leaf = ""
        if breadcrumb:
            items = breadcrumb.get("itemListElement", [])
            names = [it.get("name", "") for it in items]
            if len(names) >= 2:
                cat_l1 = names[1]
            if len(names) >= 2:
                cat_leaf = names[-2]
        # Отключённые на сайте категории (leaf «… (выкл)») не собираем.
        if "(выкл" in cat_leaf.lower():
            return None
        group = categories.classify(cat_leaf) or categories.classify(cat_l1) or group_hint

        # МУЛЬТИПРОДАВЕЦ: все предложения из payload (приоритет №1).
        arr = nuxt.parse_nuxt_data(resp.text)
        offers: list[Offer] = []
        for o in nuxt.find_offers(arr):
            offers.append(Offer(
                seller_name=o["seller"],
                price=float(o["price"]) if o.get("price") not in (None, "") else None,
                currency=config.DEFAULT_CURRENCY,
                availability=_availability_from_days(o.get("delivery_days")),
                quantity_in_stock=o.get("quantity_in_stock"),
                delivery_days=o.get("delivery_days"),
            ))
        if not offers:
            # fallback: одно предложение из JSON-LD (если payload пуст)
            on = product_node.get("offers")
            for o in (on if isinstance(on, list) else [on]):
                if not isinstance(o, dict):
                    continue
                seller = o.get("seller") or {}
                price = o.get("price")
                offers.append(Offer(
                    seller_name=seller.get("name", "") if isinstance(seller, dict) else str(seller),
                    price=float(price) if price not in (None, "") else parse_price(str(price)),
                    currency=o.get("priceCurrency", config.DEFAULT_CURRENCY),
                    availability=carcity_availability(resp.text),
                ))

        # Все характеристики товара (одно- и много-значные) из payload.
        chars = nuxt.characteristics(resp.text)
        oem = carcity_oem_numbers(chars)

        # Атрибуты: основа из названия/категории, поверх — реальные характеристики.
        cat_text = f"{cat_l1} {cat_leaf} {category_hint}".strip()
        attributes = extract_for_group(group, name, cat_text) if group else {}
        if group:
            attributes.update(attributes_from_carcity_chars(group, chars))

        # Физ-параметры из товарного узла payload (вес/габариты — не в характеристиках).
        if group:
            phys = nuxt.physical_fields(arr, name=name)
            if phys.get("weight"):  # вес товара в граммах — единый источник по всем категориям
                attributes["weight"] = f"{phys['weight']} г"
            # Габариты: только у АКБ и только если не пришли из характеристик (Длина/Ширина/Высота).
            if (group == "batteries" and not attributes.get("dimensions")
                    and all(phys.get(k) for k in ("length", "width", "height"))):
                attributes["dimensions"] = (
                    f"{phys['length']} × {phys['width']} × {phys['height']} мм"
                )

        return Product(
            source=SOURCE,
            source_product_id=_product_id(url),
            source_url=url,
            name=name,
            brand=brand,
            article_sku=article,
            category_group=group or "",
            category_l1=cat_l1,
            category_leaf=cat_leaf,
            oem_numbers=oem,
            image_url=image,
            attributes=attributes,
            offers=offers,
            parsed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
