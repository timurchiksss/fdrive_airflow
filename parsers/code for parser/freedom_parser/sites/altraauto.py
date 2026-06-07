"""Парсер altraauto.kz — кастомная серверная платформа, только шины.

Обнаружение карточек — через `sitemap-index.xml`: парсер скачивает индексный
sitemap и подбирает два типа подкарт:

* `products-shiny.xml` — обычный XML со всеми **в наличии** шинами;
* `out_of_stock-*.xml.gz` — gzip-сжатые подкарты «нет в наличии» (бывает несколько).

URL карточки кодирует ключевые атрибуты:
`/shiny/{brand}/{model}/s-{w}-{p}-{d}-{speed}-{load}-(no-)?spike-id-{N}[-...]-s.html`
Числовой `{N}` — это `source_product_id` (он же `data-id` в HTML).

Атрибуты — простой HTML без JSON-LD: `div._parameter > ul > li > span+span`.
Один продавец — сам магазин «altraauto». Цена — текстом «50 900 тг», доступность —
из блока «На заказ N шт.» (под заказ) или «В наличии: N шт.» (в наличии).
"""
from __future__ import annotations

import gzip
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import config
from freedom_parser.common.attributes import detect_runflat, detect_season, parse_price
from freedom_parser.common.http import Fetcher
from freedom_parser.common.models import Offer, Product

log = logging.getLogger("freedom_parser.altraauto")

SOURCE = "altraauto"
SELLER = "altraauto"

# Числовой id в URL: «...-id-NNNN-s.html», «...-id-NNNN-kamera-s.html»,
# «...-id-NNNN-kamera-lenta-sloi-22-s.html». Хвост между id и -s.html — опц.
_ID_RE = re.compile(r"-id-(\d+)(?:-[^/]+)*-s\.html$")

# «50 900 тг» / «370 000 тг» — допускаем обычные и неразрывные пробелы между цифр.
_PRICE_RE = re.compile(r"(\d{1,3}(?:[\s ]\d{3}){1,3}|\d{1,9})\s*тг", re.IGNORECASE)

# Активный (in-stock) блок: «С доставкой N шт.» / «В наличии[: ] N шт.»
_INSTOCK_QTY_RE = re.compile(
    r"(?:С\s+доставкой|В\s+наличии)\s*:?\s*(\d+)\s*шт", re.IGNORECASE
)
# Неактивный (warehouse) блок: «На заказ N шт.» — даже 0 валиден (склад пустой).
_BACKORDER_RE = re.compile(r"На\s+заказ\s+(\d+)\s*шт", re.IGNORECASE)

# Расположение картинок товаров: /media/product/<hash>_full.png|jpg
_IMG_PRODUCT_RE = re.compile(r"/media/product/", re.IGNORECASE)


def source_product_id_from_url(url: str) -> str:
    """Извлечь числовой id из URL карточки; '' если не распознано."""
    m = _ID_RE.search(url or "")
    return m.group(1) if m else ""


def detect_studded_from_url(url: str) -> bool:
    """`-spike-` => True, `-no-spike-` => False. Порядок проверок важен."""
    if not url:
        return False
    low = url.lower()
    if "-no-spike-" in low:
        return False
    return "-spike-" in low


# Метки блока атрибутов модели (значения берём text() второго <span> в <li>).
# «Ширина» и «Ширина сечения» — оба варианта на одинаковом ключе (грузовые шины).
_ATTR_LABELS = {
    "ширина", "ширина сечения",
    "профиль",
    "диаметр",
    "сезон",
    "бренд",
    "название",
    "артикул",
    "индекс нагрузки",
    "индекс скорости",
}


def _parse_attributes(soup: BeautifulSoup) -> dict[str, str]:
    """`div._parameter > ul > li > span+span` -> {нижнерегистровая метка: значение}."""
    out: dict[str, str] = {}
    block = soup.select_one("div._parameter ul") or soup.select_one("div._parameter")
    if block is None:
        return out
    for li in block.find_all("li"):
        spans = li.find_all("span", recursive=False)
        if len(spans) < 2:
            spans = li.find_all("span")
        if len(spans) < 2:
            continue
        label = spans[0].get_text(" ", strip=True).rstrip(":").strip().lower()
        if label not in _ATTR_LABELS:
            continue
        value = spans[1].get_text(" ", strip=True)
        if label and value and label not in out:
            out[label] = value
    return out


def _to_int(text: str | None) -> int | None:
    """Первое целое число в строке — для ширины/профиля/диаметра."""
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else None


def _load_index(text: str | None) -> str:
    """«99 — до 775 кг» -> «99»; «167 — до 5450 кг» -> «167»."""
    if not text:
        return ""
    m = re.match(r"\s*(\d+)", text)
    return m.group(1) if m else ""


def _speed_index(text: str | None) -> str:
    """«V — до 240 км/ч» -> «V»; « C — до 60 км/ч» -> «C» (ведущие пробелы ок)."""
    if not text:
        return ""
    m = re.search(r"[A-Za-zА-Яа-я]{1,2}", text)
    return m.group(0).upper() if m else ""


def _pick_image(soup: BeautifulSoup) -> str:
    """Первая картинка из /media/product/ (предпочитаем _full, fallback _320x320)."""
    full: str = ""
    thumb: str = ""
    for tag in soup.find_all(["a", "img"]):
        for attr in ("href", "src"):
            val = tag.get(attr) or ""
            if not val or not _IMG_PRODUCT_RE.search(val):
                continue
            low = val.lower()
            if "_full." in low and not full:
                full = val
            elif "_320x320." in low and not thumb:
                thumb = val
        if full:
            break
    url = full or thumb
    if url and url.startswith("/"):
        url = urljoin(config.ALTRAAUTO_BASE + "/", url.lstrip("/"))
    return url


class AltraautoScraper:
    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or Fetcher()

    def _get(self, url: str):
        """GET, устойчивый к битым ссылкам: 404/сетевая ошибка -> None."""
        try:
            return self.fetcher.get(url)
        except Exception as exc:  # noqa: BLE001
            log.warning("altraauto: пропуск %s (%s)", url, exc)
            return None

    # ---- 1. Обнаружение карточек через sitemap-index ----
    def discover(
        self,
        _unused_groups=None,
        limit: int | None = None,
    ) -> list[tuple[str, str]]:
        """[(url, 'tires'), ...] — все шины из `products-shiny.xml` + `out_of_stock-*.xml.gz`.

        Дедуп по числовому id (in-stock приоритетнее out-of-stock).
        """
        index_resp = self._get(config.ALTRAAUTO_SITEMAP_INDEX)
        if index_resp is None:
            return []
        sub_urls = re.findall(r"<loc>(.*?)</loc>", index_resp.text)
        if not sub_urls:
            return []

        # Сортируем так, чтобы in-stock прошёл раньше out-of-stock (дедуп по id).
        in_stock_subs = [u for u in sub_urls if "/products-shiny.xml" in u]
        oos_subs = [u for u in sub_urls if "/out_of_stock-" in u and u.endswith(".gz")]

        seen: dict[str, str] = {}        # id -> url (первый победил)
        out: list[tuple[str, str]] = []

        for sub in in_stock_subs + oos_subs:
            for url in self._iter_sub_sitemap(sub):
                if "/shiny/" not in url:
                    continue
                pid = source_product_id_from_url(url)
                if not pid or pid in seen:
                    continue
                seen[pid] = url
                out.append((url, "tires"))
                if limit and len(out) >= limit:
                    log.info("altraauto: достигнут limit=%d", limit)
                    return out

        log.info("altraauto: карточек к разбору %d (in-stock + out-of-stock)", len(out))
        return out

    def _iter_sub_sitemap(self, sub_url: str):
        """Yield <loc> URLs из подкарты (plain XML или gzip-bytes для .gz)."""
        resp = self._get(sub_url)
        if resp is None:
            return
        if sub_url.endswith(".gz"):
            try:
                raw = gzip.decompress(resp.content)
                text = raw.decode("utf-8", errors="replace")
            except (OSError, EOFError) as exc:
                log.warning("altraauto: битый gzip %s (%s)", sub_url, exc)
                return
        else:
            text = resp.text
        for loc in re.findall(r"<loc>(.*?)</loc>", text):
            yield loc.strip()

    # ---- 2. Разбор страницы товара ----
    def parse(self, url: str, _root: str = "shiny") -> Product | None:
        pid = source_product_id_from_url(url)
        if not pid:
            log.warning("altraauto: не распознан id в %s", url)
            return None

        resp = self._get(url)
        if resp is None:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Имя
        h1 = soup.find("h1")
        name = h1.get_text(" ", strip=True) if h1 else ""

        attrs = _parse_attributes(soup)

        brand = attrs.get("бренд", "").strip()
        article_sku = attrs.get("артикул", "").strip()

        width = _to_int(attrs.get("ширина") or attrs.get("ширина сечения"))
        profile = _to_int(attrs.get("профиль"))
        diameter = _to_int(attrs.get("диаметр"))
        season = detect_season(attrs.get("сезон"))
        load_index = _load_index(attrs.get("индекс нагрузки"))
        speed_index = _speed_index(attrs.get("индекс скорости"))

        studded = detect_studded_from_url(url)
        runflat = detect_runflat(name)

        # Цена — берём из <span itemprop="price" content="N"> (точное число, без шума
        # вроде «доставка 0 тг» в тексте страницы). Fallback: первое «N тг» в тексте.
        price: float | None = None
        ptag = soup.find(attrs={"itemprop": "price"})
        if ptag is not None:
            raw = ptag.get("content") or ptag.get_text(" ", strip=True)
            try:
                val = float(re.sub(r"[\s ]", "", raw))
                price = val if val > 0 else None
            except (TypeError, ValueError):
                price = None
        if price is None:
            page_text = soup.get_text(" ", strip=True)
            m = _PRICE_RE.search(page_text)
            if m:
                p = parse_price(m.group(1))
                price = p if (p is not None and p > 0) else None

        # Доступность определяем по ЦЕНЕ, а не по блокам. На out-of-stock странице
        # тоже есть «активные» _product_cart_row (например, информация о доставке),
        # но <meta itemprop="price" content="0"> и текст «Товара нет в наличии».
        # Самый надёжный сигнал: реальная цена > 0 => «В наличии», иначе «Под заказ».
        availability = "В наличии" if (price is not None and price > 0) else "Под заказ"
        quantity_in_stock: int | None = None
        if availability == "В наличии":
            # qty из активного «С доставкой N шт.» / «В наличии: N шт.»;
            # fallback — тот же паттерн где угодно в тексте (синтетические фикстуры/редкие лейауты).
            for row in soup.select("._product_cart_row"):
                if "_inactive" in (row.get("class") or []):
                    continue
                m = _INSTOCK_QTY_RE.search(row.get_text(" ", strip=True))
                if m:
                    quantity_in_stock = int(m.group(1))
                    break
            if quantity_in_stock is None:
                page_text = soup.get_text(" ", strip=True)
                m = _INSTOCK_QTY_RE.search(page_text)
                if m:
                    quantity_in_stock = int(m.group(1))

        image_url = _pick_image(soup)

        product_attrs: dict[str, object] = {
            "tire_width": width,
            "tire_profile": profile,
            "tire_diameter": diameter,
            "load_index": load_index,
            "speed_index": speed_index,
            "season": season,
            "runflat": runflat,
            "studded": studded,
        }

        return Product(
            source=SOURCE,
            source_product_id=pid,
            source_url=url,
            name=name,
            brand=brand,
            article_sku=article_sku,
            category_group="tires",
            category_l1="Шины",
            category_leaf="Шины altraauto",
            image_url=image_url,
            attributes=product_attrs,
            offers=[Offer(
                seller_name=SELLER,
                price=price,
                currency=config.DEFAULT_CURRENCY,
                availability=availability,
                quantity_in_stock=quantity_in_stock,
            )],
            parsed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
