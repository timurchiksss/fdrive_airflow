"""Парсер expertoil.kz — масла и АКБ, server-rendered HTML (PHP/nginx).

Структура каталога:
  /ru/catalog/masla_490/?p=N         — листинг масел (пагинация ?p=1,2,...)
  /ru/catalog/akkumulyatory_490/?p=N — листинг АКБ
  /ru/catalog/{brand_slug}/{product-slug}  — карточка товара

Особенности (см. Phase A анализ):
  - Schema.org / JSON-LD / OG отсутствуют полностью. Только серверный HTML.
  - У большинства карточек блока характеристик НЕТ (только h1/цена/корзина/картинка).
    У части карточек контент-редактор вставил скопированный из Yandex.Market HTML —
    в нём строки key/value выглядят как `span[data-auto="product-spec"]` (метка)
    и соседний `div.b2ZT4` (значение). Поэтому атрибуты, по большей части, будут
    извлекаться из НАЗВАНИЯ (extract_for_group).
  - Цена: `div.el_desc span.price` -> текст «34 100 тг.».
  - Кнопка «В корзину»: `<a class="button" onclick="add_to_basket1(NNN)">` —
    наличие этой кнопки = «В наличии», отсутствие = «Под заказ».
  - Картинка: `div.el_img img@src` (`/upload/images/big/...`), fallback на оригинал
    (`a[rel="image"]@href` -> `/upload/images/...`).
  - Бренд: из URL-сегмента (`/ru/catalog/{brand}_{id}/...`), напр.:
      shell_521          -> Shell
      akb-exide_383      -> Exide
      united-oil_...     -> United Oil
      castrol_532        -> Castrol
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import config
from freedom_parser.common.attributes import (
    attributes_from_carcity_chars,
    extract_for_group,
    parse_price,
)
from freedom_parser.common.http import Fetcher
from freedom_parser.common.models import Offer, Product

log = logging.getLogger("freedom_parser.expertoil")

SOURCE = "expertoil"
SELLER = "expertoil"
CITY = "Алматы"
MAX_PAGES = 200  # предохранитель от бесконечной пагинации

# «Цена: 34 100 тг.» — допускаем обычные и неразрывные пробелы между цифр.
_PRICE_TEXT_RE = re.compile(r"Цена\s*:?\s*([\d\s ]+)\s*тг", re.IGNORECASE)

_LEAF_BY_ROOT = {
    "oils": "Масла expertoil",
    "batteries": "Аккумуляторы expertoil",
}
_L1_BY_ROOT = {
    "oils": "Масла",
    "batteries": "Аккумуляторы",
}
_LISTING_BY_ROOT = {
    "oils": config.EXPERTOIL_OILS_LISTING,
    "batteries": config.EXPERTOIL_BATTERIES_LISTING,
}


def _normalize_brand(brand_seg: str) -> str:
    """`shell_521` -> `Shell`; `akb-exide_383` -> `Exide`; `united-oil_...` -> `United Oil`.

    Алгоритм:
      1) отбрасываем числовой суффикс после `_` (id категории/бренда);
      2) у АКБ-сегментов снимаем префикс `akb-`;
      3) дефисы -> пробелы;
      4) Title Case.
    """
    if not brand_seg:
        return ""
    seg = brand_seg.split("_")[0].rstrip("-")
    if seg.startswith("akb-"):
        seg = seg[len("akb-"):]
    seg = seg.replace("-", " ").strip()
    # Схлопываем множественные пробелы: «petro---canada-» -> «petro   canada» -> «Petro Canada».
    seg = re.sub(r"\s+", " ", seg)
    return seg.title()


def _brand_from_url(url: str) -> str:
    """Берём бренд из пути `/ru/catalog/{brand_seg}/{slug}`."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    # ['ru', 'catalog', '{brand_seg}', '{slug}']
    if len(parts) >= 3 and parts[0] == "ru" and parts[1] == "catalog":
        return _normalize_brand(parts[2])
    return ""


def _source_product_id(url: str) -> str:
    """ID = путь после `/ru/catalog/` (включая бренд-сегмент)."""
    path = urlparse(url).path
    if "/ru/catalog/" in path:
        return path.split("/ru/catalog/", 1)[1].strip("/")
    return path.strip("/")


def _extract_chars(soup: BeautifulSoup) -> dict[str, str]:
    """Достаём словарь характеристик {лейбл: значение} с тремя fallback-ами.

    Структура зависит от карточки:
      A) Yandex.Market inject (большинство карточек expertoil):
         `span[data-auto="product-spec"]` — лейбл, соседний `div.b2ZT4` — значение.
      B) Классический dl > dt+dd (пары).
      C) Классический table > tr > td:nth-child(1)+td:nth-child(2).
      D) div.params > div.row с двумя вложенными span/div.

    Возвращает {} если ничего не нашли — это норма для expertoil.
    """
    out: dict[str, str] = {}

    # A) Yandex.Market injected block ----------------------------------------
    for lbl in soup.select('span[data-auto="product-spec"]'):
        label = lbl.get_text(" ", strip=True).rstrip(":").strip()
        if not label or label in out:
            continue
        # Значение — ближайший `div.b2ZT4` в том же ряду (общий предок _3rW2x).
        row = lbl
        for _ in range(6):  # подняться до контейнера строки
            row = row.parent
            if row is None:
                break
            val_node = row.select_one("div.b2ZT4") if hasattr(row, "select_one") else None
            if val_node is not None:
                value = val_node.get_text(" ", strip=True)
                if value:
                    out[label] = value
                break

    # B) dl / dt+dd ----------------------------------------------------------
    if not out:
        for dl in soup.find_all("dl"):
            items = dl.find_all(["dt", "dd"])
            i = 0
            while i + 1 < len(items):
                a, b = items[i], items[i + 1]
                if a.name == "dt" and b.name == "dd":
                    label = a.get_text(" ", strip=True).rstrip(":").strip()
                    value = b.get_text(" ", strip=True)
                    if label and value and label not in out:
                        out[label] = value
                    i += 2
                else:
                    i += 1

    # C) table > tr > td+td --------------------------------------------------
    if not out:
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 2:
                    continue
                label = tds[0].get_text(" ", strip=True).rstrip(":").strip()
                value = tds[1].get_text(" ", strip=True)
                if label and value and label not in out:
                    out[label] = value

    # D) div.params > div.row > span+span / div+div --------------------------
    if not out:
        for row in soup.select("div.params div.row, div.params .param-row, div.params > div"):
            children = [c for c in row.find_all(["span", "div"], recursive=False) if c.get_text(strip=True)]
            if len(children) < 2:
                continue
            label = children[0].get_text(" ", strip=True).rstrip(":").strip()
            value = children[1].get_text(" ", strip=True)
            if label and value and label not in out:
                out[label] = value

    return out


def _chars_to_carcity_format(chars: dict[str, str]) -> dict[str, list[str]]:
    """`{label: value}` -> `{label: [value]}` для совместимости с
    attributes_from_carcity_chars (которая ожидает много-значный словарь).
    """
    return {k: [v] for k, v in chars.items() if v}


def _pick_image(soup: BeautifulSoup) -> str:
    """Главная картинка: `div.el_img img@src` (/upload/images/big/...); fallback —
    `a[rel='image']@href` (/upload/images/...). Возвращаем абсолютный URL.
    """
    img = soup.select_one("div.el_img img")
    src = img.get("src") if img else None
    if not src:
        a = soup.select_one("div.el_img a[rel='image']")
        if a is not None:
            src = a.get("href")
    if not src:
        return ""
    return urljoin(config.EXPERTOIL_BASE, src)


class ExpertoilScraper:
    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or Fetcher()

    def _get(self, url: str):
        """GET, устойчивый к битым ссылкам: 404/сетевая ошибка -> None."""
        try:
            return self.fetcher.get(url)
        except Exception as exc:  # noqa: BLE001
            log.warning("expertoil: пропуск %s (%s)", url, exc)
            return None

    # ---- 1. Обнаружение карточек: листинги масел и АКБ постранично ----
    def _product_urls_on_listing(self, listing_url: str, root: str) -> list[tuple[str, str]]:
        """Один листинг -> [(url, root), ...] по всем страницам ?p=1,2,..."""
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            sep = "&" if "?" in listing_url else "?"
            url = f"{listing_url}{sep}p={page}"
            resp = self._get(url)
            if resp is None:
                break
            soup = BeautifulSoup(resp.text, "lxml")
            # Карточки в листинге: ul.products-grid > li.item > div.product-shop
            #   > h2.product-name > a[href]. У части карточек ссылка дублируется
            #   и в `div.actions a` — селектор по h2 даёт ровно один URL на карточку.
            anchors = soup.select("ul.products-grid h2.product-name a[href]")
            if not anchors:
                break
            new = 0
            for a in anchors:
                href = (a.get("href") or "").strip()
                if not href:
                    continue
                purl = urljoin(config.EXPERTOIL_BASE, href).split("#")[0]
                if purl in seen:
                    continue
                seen.add(purl)
                out.append((purl, root))
                new += 1
            if new == 0:
                break
        return out

    def discover(self, _unused_groups=None,
                 limit: int | None = None) -> list[tuple[str, str]]:
        """[(product_url, root)] — масла + АКБ. Дедуп по URL. limit обрезает общее число."""
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for listing, root in (
            (config.EXPERTOIL_OILS_LISTING, "oils"),
            (config.EXPERTOIL_BATTERIES_LISTING, "batteries"),
        ):
            log.info("expertoil: листинг %s (%s)", listing, root)
            for url, r in self._product_urls_on_listing(listing, root):
                if url in seen:
                    continue
                seen.add(url)
                out.append((url, r))
                if limit and len(out) >= limit:
                    log.info("expertoil: достигнут limit=%d", limit)
                    return out
        log.info("expertoil: карточек к разбору %d", len(out))
        return out

    # ---- 2. Разбор страницы товара ----
    def parse(self, url: str, root: str = "oils") -> Product | None:
        resp = self._get(url)
        if resp is None:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Имя
        h1 = soup.find("h1")
        name = h1.get_text(" ", strip=True) if h1 else ""
        if not name:
            log.warning("expertoil: нет h1 на %s", url)
            return None

        # Бренд: из URL (стабильно), fallback — из лейбла «Бренд» в chars.
        brand = _brand_from_url(url)

        # Характеристики (часто пусто — это норма).
        chars = _extract_chars(soup)
        if not brand:
            brand = chars.get("Бренд", "").strip()

        # Цена: regex по всему тексту страницы.
        price: float | None = None
        page_text = soup.get_text(" ", strip=True)
        m = _PRICE_TEXT_RE.search(page_text)
        if m:
            p = parse_price(m.group(1))
            price = p if (p is not None and p > 0) else None

        # Наличие: кнопка «В корзину» есть -> «В наличии», иначе «Под заказ».
        cart_btn = soup.select_one("a.add-to-cart") or soup.select_one("a.button")
        has_cart = False
        if cart_btn is not None:
            txt = cart_btn.get_text(" ", strip=True).lower()
            if "корзин" in txt:
                has_cart = True
        if not has_cart and "в корзину" in page_text.lower():
            has_cart = True
        availability = "В наличии" if has_cart else "Под заказ"

        # Атрибуты: из chars (как у car-city) + добор по названию.
        attributes: dict[str, object] = {}
        if root in ("oils", "batteries"):
            attributes.update(
                attributes_from_carcity_chars(root, _chars_to_carcity_format(chars))
            )
            # Поверх — добор из имени (вязкость/объём масла, ёмкость АКБ и т.д.):
            # extract_for_group возвращает None/пусто для отсутствующих — не затираем.
            from_name = extract_for_group(root, name)
            for k, v in from_name.items():
                if k in attributes and attributes[k] not in (None, "", []):
                    continue  # уже есть из chars — приоритет у структурного источника
                if v in (None, ""):
                    continue
                attributes[k] = v
            if root == "batteries":
                # voltage_v не указан на сайте; для автомобильных АКБ дефолт = 12.
                attributes.setdefault("voltage_v", 12)
                # polarity — из имени («правый»/«левый»/«обратная»/«прямая»).
                from freedom_parser.common.attributes import detect_battery_polarity
                if not attributes.get("polarity"):
                    pol = detect_battery_polarity(name)
                    if pol:
                        attributes["polarity"] = pol

        image_url = _pick_image(soup)

        return Product(
            source=SOURCE,
            source_product_id=_source_product_id(url),
            source_url=url,
            name=name,
            brand=brand,
            article_sku="",
            category_group=root,
            category_l1=_L1_BY_ROOT.get(root, ""),
            category_leaf=_LEAF_BY_ROOT.get(root, ""),
            image_url=image_url,
            attributes=attributes,
            offers=[Offer(
                seller_name=SELLER,
                price=price,
                currency=config.DEFAULT_CURRENCY,
                availability=availability,
                quantity_in_stock=None,
                city=CITY,
            )],
            parsed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
