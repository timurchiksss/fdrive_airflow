"""Парсер pitstopshop (pitstopshop.kz) — OpenCart, только шины, server-rendered.

Двухуровневая структура (проверено на raw HTML):
  1) /catalog/{root}/                -> ссылки брендов  /catalog/{root}/{brand}/
  2) /catalog/{root}/{brand}/        -> ссылки моделей /catalog/{root}/{brand}/{model}/
  3) /catalog/{root}/{brand}/{model}/ -> блок атрибутов модели + таблицы размеров:
        #tab-sale     — в наличии (с ценами)
        #tab-soldout  — нет в наличии (без цен)

КАЖДЫЙ размер (строка таблицы) = отдельный товар (1 строка CSV). Атрибуты модели
(brand, brand_country, model_name, season, studded, tire_type) дублируются в каждый
размер. Продавец один — сам магазин (мультипродавца здесь нет).

Размер берём из slug ссылки (надёжно), с fallback на разбор из названия.
JSON-LD на сайте нет — парсим HTML (BeautifulSoup).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import config
from freedom_parser.common.attributes import (
    detect_runflat,
    detect_season,
    parse_price,
    parse_studded,
    parse_tire_size,
    tire_size_from_pitstop_slug,
)
from freedom_parser.common.http import Fetcher
from freedom_parser.common.models import Offer, Product

log = logging.getLogger("freedom_parser.pitstopshop")

SOURCE = "pitstopshop"
SELLER = "PitStopShop"

# Раздел -> листовая категория.
ROOT_LEAF = {
    "tyre": "Легковые шины",
    "gruz": "Грузовые шины",
    "sh": "Сельхоз шины",
    "moto": "Мото шины",
    "atv": "Квадро шины (ATV)",
}

# Метки блока атрибутов модели.
_ATTR_LABELS = ("Производитель", "Название модели", "Тип автомобиля", "Сезонность", "Шипы")

# Цена в строке: число непосредственно перед «т.»/₸/тг — якорь на суффиксе, чтобы не
# поймать «15» из «R15».
_PRICE_TOKEN_RE = re.compile(r"(\d[\d\s ]*\d|\d)\s*(?:т\.|₸|тг|тенге)", re.IGNORECASE)
_QTY_RE = re.compile(r"(\d+)\s*шт\.?")        # «3 шт.» -> остаток (индикатор низкого склада)
_XL_RE = re.compile(r"\bXL\b", re.IGNORECASE)
_RF_MARK_RE = re.compile(r"\bRF\b", re.IGNORECASE)


def _catalog_segments(url: str) -> list[str] | None:
    """Сегменты пути после /catalog/: '/catalog/tyre/maxxis/at-771/' -> ['tyre','maxxis','at-771']."""
    path = urlparse(url).path
    if "/catalog/" not in path:
        return None
    rest = path.split("/catalog/", 1)[1].strip("/")
    return [s for s in rest.split("/") if s]


def _row_price(text: str) -> float | None:
    m = _PRICE_TOKEN_RE.search(text or "")
    return parse_price(m.group(1)) if m else None


def _map_studded(value: str | None) -> bool | None:
    """«Шипы: нет/да/шипованная» -> False/True; пусто -> None."""
    if not value:
        return None
    low = value.strip().lower()
    if low in ("нет", "no", "-", "—"):
        return False
    if "да" in low or "есть" in low or "шип" in low:
        return True
    return parse_studded(value)


class PitStopShopScraper:
    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or Fetcher()

    def _get(self, url: str):
        """GET, устойчивый к битым ссылкам: 404/ошибка -> None (не валит обход)."""
        try:
            return self.fetcher.get(url)
        except Exception as exc:  # noqa: BLE001
            log.warning("pitstopshop: пропуск %s (%s)", url, exc)
            return None

    # ---- 1. Обнаружение моделей через sitemap ----
    def discover(self, roots: list[str] | None = None,
                 limit: int | None = None) -> list[tuple[str, str]]:
        """[(model_url, root)] из sitemap.xml — модельные страницы выбранных разделов.

        ВАЖНО: страница бренда отдаёт максимум 100 моделей и НЕ пагинируется
        (`?page=`/`/2/`/`?limit=` игнорируются), поэтому полный список берём из
        sitemap — там, напр., у Michelin 164 модели против 100 на странице бренда.
        sitemap содержит только модельные URL (3 сегмента), без страниц размеров.
        """
        roots = set(roots or config.PITSTOP_DEFAULT_ROOTS)
        resp = self._get(config.PITSTOP_SITEMAP)
        if resp is None:
            return []
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for u in re.findall(r"<loc>(.*?)</loc>", resp.text):
            segs = _catalog_segments(u)
            if not segs or len(segs) != 3 or segs[0] not in roots:
                continue                          # только модели выбранных разделов
            url = u if u.endswith("/") else u + "/"
            if url in seen:
                continue
            seen.add(url)
            out.append((url, segs[0]))
            log.debug("pitstopshop: модель %s", url)
            if limit and len(out) >= limit:
                break
        log.info("pitstopshop: моделей к разбору %d (разделы: %s)",
                 len(out), ", ".join(sorted(roots)))
        return out

    # ---- 3. Разбор страницы модели -> размеры ----
    @staticmethod
    def _model_attributes(soup: BeautifulSoup) -> dict[str, str]:
        """Блок <li><strong>Label:</strong> value</li> -> {label: value}.

        Для «Производитель» дополнительно возвращает brand (текст <a>) и страну в скобках.
        """
        out: dict[str, str] = {}
        for li in soup.find_all("li"):
            strong = li.find("strong")
            if not strong:
                continue
            label = strong.get_text(strip=True).rstrip(":").strip()
            if label not in _ATTR_LABELS or label in out:
                continue
            full = li.get_text(" ", strip=True)
            value = re.sub(r"^\s*" + re.escape(strong.get_text(strip=True)), "", full).strip()
            out[label] = value
            if label == "Производитель":
                a = li.find("a")
                if a and a.get_text(strip=True):
                    out["_brand"] = a.get_text(strip=True)
                country = re.search(r"\(([^)]+)\)", value)
                if country:
                    out["_brand_country"] = country.group(1).strip()
        return out

    def parse(self, model_url: str, root: str = "tyre") -> list[Product]:
        if not model_url.endswith("/"):
            model_url += "/"
        resp = self._get(model_url)
        if resp is None:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        model_segs = _catalog_segments(model_url) or []
        if len(model_segs) < 3:
            return []

        attrs_block = self._model_attributes(soup)
        brand = attrs_block.get("_brand", "").strip()
        if not brand:
            brand = (model_segs[1] if len(model_segs) > 1 else "").replace("-", " ").title()
        brand_country = attrs_block.get("_brand_country", "")
        model_name = attrs_block.get("Название модели", "")
        tire_type = attrs_block.get("Тип автомобиля", "")
        model_season = detect_season(attrs_block.get("Сезонность", ""))
        model_studded = _map_studded(attrs_block.get("Шипы"))

        og = soup.find("meta", property="og:image")
        image_url = og.get("content", "") if og else ""

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        leaf = ROOT_LEAF.get(root, f"Шины ({root})")

        products: list[Product] = []
        seen_ids: set[str] = set()
        # Сначала «в наличии» (с ценой), потом «нет в наличии» — при дедупе цена в приоритете.
        for tab_id, in_stock in (("#tab-sale", True), ("#tab-soldout", False)):
            container = soup.select_one(tab_id)
            if container is None:
                continue
            for a in container.find_all("a", href=True):
                size_url = urljoin(model_url, a["href"]).split("?")[0].split("#")[0]
                segs = _catalog_segments(size_url)
                if not segs or len(segs) != 4 or segs[:3] != model_segs[:3]:
                    continue  # не размер этой модели
                if not size_url.endswith("/"):
                    size_url += "/"
                spid = "/".join(segs)                      # включает раздел: tyre/maxxis/...
                if spid in seen_ids:
                    continue
                seen_ids.add(spid)

                raw_name = a.get_text(" ", strip=True)
                qty_m = _QTY_RE.search(raw_name)
                quantity = int(qty_m.group(1)) if qty_m else None
                name = _QTY_RE.sub("", raw_name).strip(" .,")   # имя без «N шт.»

                # Размер из slug (позиционно полнее по load/speed), название — fallback.
                size = tire_size_from_pitstop_slug(size_url)
                if not size.get("tire_width"):
                    size = parse_tire_size(name)

                # reinforced и runflat — НЕЗАВИСИМО (шина бывает XL и RunFlat сразу).
                reinforced = ""
                speed = str(size.get("speed_index") or "")
                if speed.upper() in ("XL", "RF"):           # маркер усиления попал в «скорость»
                    reinforced = speed.upper()
                    size["speed_index"] = ""
                if not reinforced:
                    if _XL_RE.search(name) or "-xl-" in size_url.lower():
                        reinforced = "XL"
                    elif _RF_MARK_RE.search(name):
                        reinforced = "RF"

                attrs = {
                    "tire_width": size.get("tire_width"),
                    "tire_profile": size.get("tire_profile"),
                    "tire_diameter": size.get("tire_diameter"),
                    "load_index": size.get("load_index", ""),
                    "speed_index": size.get("speed_index", ""),
                    "season": model_season or detect_season(name),
                    "runflat": detect_runflat(name),
                    "studded": model_studded if model_studded is not None else parse_studded(name),
                    "model_name": model_name,
                    "tire_type": tire_type,
                    "brand_country": brand_country,
                    "reinforced": reinforced,
                }

                row = a.find_parent("tr")
                price = _row_price(row.get_text(" ", strip=True)) if (in_stock and row) else None
                products.append(Product(
                    source=SOURCE,
                    source_product_id=spid,
                    source_url=size_url,
                    name=name,
                    brand=brand,
                    article_sku="",                         # артикул только на стр. размера — не тянем
                    category_group="tires",
                    category_l1="Шины",
                    category_leaf=leaf,
                    image_url=image_url,
                    attributes=attrs,
                    offers=[Offer(
                        seller_name=SELLER,
                        price=price,
                        currency=config.DEFAULT_CURRENCY,
                        availability="В наличии" if in_stock else "Под заказ",
                        quantity_in_stock=quantity,
                    )],
                    parsed_at=now,
                ))
        return products
