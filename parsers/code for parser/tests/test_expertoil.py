"""Тесты парсера expertoil.kz (?p= пагинация, разбор карточек масел и АКБ).

Phase A показала: у большинства карточек структурного блока характеристик НЕТ
(только h1/цена/корзина/картинка). У части — вставлен HTML из Yandex.Market с
`span[data-auto="product-spec"]` (метка) и `div.b2ZT4` (значение). Атрибуты, в
основном, добываются из НАЗВАНИЯ (extract_for_group).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from freedom_parser.sites.expertoil import (
    ExpertoilScraper,
    _brand_from_url,
    _normalize_brand,
    _source_product_id,
)

BASE = config.EXPERTOIL_BASE


class _FakeResp:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.content = text.encode("utf-8")


class _FakeFetcher:
    def __init__(self, pages: dict[str, _FakeResp]) -> None:
        self.pages = pages

    def get(self, url: str):
        return self.pages.get(url)


def _page(url: str, html: str, root: str = "oils"):
    sc = ExpertoilScraper(_FakeFetcher({url: _FakeResp(html)}))
    return sc.parse(url, root=root)


# ============================================================
# (a) discover: page1 содержит 2 div.product-item, page2 пустая
# ============================================================
def test_discover_paginates_until_empty():
    p1 = """
    <html><body>
      <ul class="products-grid">
        <li><h2 class="product-name"><a href="/ru/catalog/shell_521/maslo-1">Маслo 1</a></h2></li>
        <li><h2 class="product-name"><a href="/ru/catalog/shell_521/maslo-2">Маслo 2</a></h2></li>
      </ul>
    </body></html>
    """
    p2_empty = "<html><body><p>Пусто</p></body></html>"
    pages = {
        f"{config.EXPERTOIL_OILS_LISTING}?p=1": _FakeResp(p1),
        f"{config.EXPERTOIL_OILS_LISTING}?p=2": _FakeResp(p2_empty),
        # АКБ-листинг пустой сразу
        f"{config.EXPERTOIL_BATTERIES_LISTING}?p=1": _FakeResp(p2_empty),
    }
    sc = ExpertoilScraper(_FakeFetcher(pages))
    items = sc.discover()
    urls = [u for u, _ in items]
    roots = [r for _, r in items]
    assert len(items) == 2
    assert urls == [
        f"{BASE}/ru/catalog/shell_521/maslo-1",
        f"{BASE}/ru/catalog/shell_521/maslo-2",
    ]
    assert roots == ["oils", "oils"]


# ============================================================
# (b) parse motor oil — Shell Helix Ultra 0w20 5л
# ============================================================
# HTML повторяет реальную структуру expertoil + Yandex.Market injected chars.
_OIL_HTML = """
<html><body>
<div class="el_img">
  <a title="" href="/upload/images/85872_503141_16.jpeg" rel="image">
    <img src="/upload/images/big/85872_503141_16.jpeg" />
  </a>
</div>
<div class="el_desc">
  <h1>Масло моторное SHELL HELIX Ultra 0w20 5л</h1>
  <div>Цена: <span class="price">34 100 тг.</span></div>
  <div>
    <input class="quantity_wanted" type="text" name="koll" value="1">
    <a title="В корзину" class="button" onclick="javascript: add_to_basket1(16955);"><span>В корзину</span></a>
  </div>
</div>
<div style="margin:0 0 20px">
  <div class="zh0TB">
    <div class="MAXcE">
      <div class="_3rW2x">
        <div class="_1IaDe"><div class="_6DaYY">
          <span data-auto="product-spec">Бренд</span>
        </div></div>
        <div class="eXP5k"><div class="b2ZT4">SHELL</div></div>
      </div>
      <div class="_3rW2x">
        <div class="_1IaDe"><div class="_6DaYY">
          <span data-auto="product-spec">Объем</span>
        </div></div>
        <div class="eXP5k"><div class="b2ZT4">5 л</div></div>
      </div>
      <div class="_3rW2x">
        <div class="_1IaDe"><div class="_6DaYY">
          <span data-auto="product-spec">Тип масла</span>
        </div></div>
        <div class="eXP5k"><div class="b2ZT4">синтетическое</div></div>
      </div>
      <div class="_3rW2x">
        <div class="_1IaDe"><div class="_6DaYY">
          <span data-auto="product-spec">Класс вязкости SAE</span>
        </div></div>
        <div class="eXP5k"><div class="b2ZT4">0W-20</div></div>
      </div>
    </div>
  </div>
</div>
</body></html>
"""

_OIL_URL = f"{BASE}/ru/catalog/shell_521/maslo-motornoe-shell-helix-ultra-0w20-5l"


def test_parse_oil_basic_fields():
    p = _page(_OIL_URL, _OIL_HTML, root="oils")
    assert p is not None
    assert p.name == "Масло моторное SHELL HELIX Ultra 0w20 5л"
    assert p.brand == "Shell"
    assert p.category_group == "oils"
    assert p.category_l1 == "Масла"
    assert p.category_leaf == "Масла expertoil"
    assert p.source == "expertoil"
    assert p.source_product_id == "shell_521/maslo-motornoe-shell-helix-ultra-0w20-5l"
    # картинка — абсолютный URL из /upload/images/big/...
    assert p.image_url == f"{BASE}/upload/images/big/85872_503141_16.jpeg"


def test_parse_oil_attributes_from_chars_and_name():
    p = _page(_OIL_URL, _OIL_HTML, root="oils")
    a = p.attributes
    assert a.get("viscosity") == "0W-20"
    assert a.get("volume_liters") == 5.0
    # «синтетическое» -> detect_oil_type -> «Синтетическое»
    assert "Синтет" in str(a.get("oil_type", ""))


def test_parse_oil_price_and_availability():
    p = _page(_OIL_URL, _OIL_HTML, root="oils")
    assert p.offers[0].price == 34100.0
    assert p.offers[0].currency == "KZT"
    assert p.offers[0].availability == "В наличии"
    assert p.offers[0].seller_name == "expertoil"
    assert p.offers[0].city == "Алматы"


# ============================================================
# (c) parse battery — Exide EK 700 70Ah правый
# ============================================================
_BATT_HTML = """
<html><body>
<div class="el_img">
  <a href="/upload/images/41536_445380_15.jpg" rel="image">
    <img src="/upload/images/big/41536_445380_15.jpg" />
  </a>
</div>
<div class="el_desc">
  <h1>АКБ EXIDE EK 700 70 Ah прямая полярность</h1>
  <div>Цена: <span class="price">94 500 тг.</span></div>
  <a title="В корзину" class="button" onclick="javascript: add_to_basket1(5454);"><span>В корзину</span></a>
</div>
<div style="margin:0 0 20px">
  <div class="MAXcE">
    <div class="_3rW2x">
      <div class="_1IaDe"><div class="_6DaYY">
        <span data-auto="product-spec">Емкость</span>
      </div></div>
      <div class="eXP5k"><div class="b2ZT4">70 А·ч</div></div>
    </div>
    <div class="_3rW2x">
      <div class="_1IaDe"><div class="_6DaYY">
        <span data-auto="product-spec">Полярность</span>
      </div></div>
      <div class="eXP5k"><div class="b2ZT4">Прямая</div></div>
    </div>
  </div>
</div>
</body></html>
"""

_BATT_URL = f"{BASE}/ru/catalog/akb-exide_383/akb-exide-ek-700-70-ah--pravyy-_26636"


def test_parse_battery_capacity_and_polarity():
    p = _page(_BATT_URL, _BATT_HTML, root="batteries")
    assert p is not None
    assert "EXIDE EK 700" in p.name
    a = p.attributes
    # ёмкость — из chars (70 А·ч)
    assert a.get("capacity_ah") == 70
    # полярность — из chars («Прямая») или из текста («прямая полярность»)
    assert a.get("polarity") in ("Прямая", "Обратная")
    assert a.get("polarity") == "Прямая"
    assert p.category_group == "batteries"
    assert p.category_leaf == "Аккумуляторы expertoil"


def test_parse_battery_price_and_brand():
    p = _page(_BATT_URL, _BATT_HTML, root="batteries")
    # brand из URL-сегмента: akb-exide_383 -> Exide
    assert p.brand == "Exide"
    assert p.offers[0].price == 94500.0
    assert p.offers[0].availability == "В наличии"


# ============================================================
# (d) Цена 0 тг -> price=None
# ============================================================
def test_price_zero_returns_none():
    html = """
    <html><body>
    <div class="el_desc">
      <h1>Test 1L</h1>
      <div>Цена: <span class="price">0 тг.</span></div>
      <a title="В корзину" class="button" onclick="add_to_basket1(1);"><span>В корзину</span></a>
    </div>
    </body></html>
    """
    url = f"{BASE}/ru/catalog/shell_521/test"
    p = _page(url, html, root="oils")
    assert p is not None
    assert p.offers[0].price is None


# ============================================================
# (e) availability: нет add-to-cart и нет «В корзину» -> «Под заказ»
# ============================================================
def test_availability_no_cart_button():
    html = """
    <html><body>
    <div class="el_desc">
      <h1>Test product 1L</h1>
      <div>Цена: <span class="price">10 000 тг.</span></div>
      <p>Товар временно недоступен</p>
    </div>
    </body></html>
    """
    url = f"{BASE}/ru/catalog/shell_521/no-cart"
    p = _page(url, html, root="oils")
    assert p is not None
    assert p.offers[0].availability == "Под заказ"


# ============================================================
# (f) brand normalize
# ============================================================
def test_brand_normalize_shell():
    assert _normalize_brand("shell_521") == "Shell"


def test_brand_normalize_akb_exide():
    assert _normalize_brand("akb-exide_383") == "Exide"


def test_brand_normalize_akb_bars():
    assert _normalize_brand("akb-bars-_500") == "Bars"


def test_brand_normalize_united_oil():
    assert _normalize_brand("united-oil_777") == "United Oil"


def test_brand_from_url():
    assert _brand_from_url(f"{BASE}/ru/catalog/shell_521/foo") == "Shell"
    assert _brand_from_url(f"{BASE}/ru/catalog/akb-exide_383/bar") == "Exide"


def test_source_product_id_basic():
    assert _source_product_id(_OIL_URL) == "shell_521/maslo-motornoe-shell-helix-ultra-0w20-5l"
    assert _source_product_id(_BATT_URL) == "akb-exide_383/akb-exide-ek-700-70-ah--pravyy-_26636"
