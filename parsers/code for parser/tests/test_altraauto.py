"""Тесты парсера altraauto.kz (sitemap-index discovery, HTML attr block)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freedom_parser.sites.altraauto import (
    AltraautoScraper,
    detect_studded_from_url,
    source_product_id_from_url,
)

BASE = "https://altraauto.kz"


class _FakeResp:
    def __init__(self, text: str = "", content: bytes | None = None) -> None:
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")


class _FakeFetcher:
    def __init__(self, pages: dict[str, _FakeResp]) -> None:
        self.pages = pages

    def get(self, url: str) -> _FakeResp | None:
        return self.pages.get(url)


def _page(url: str, html: str) -> "Product | None":  # noqa: F821 — type-hint only
    sc = AltraautoScraper(_FakeFetcher({url: _FakeResp(html)}))
    return sc.parse(url)


# ---- 1-3. Числовой id из URL (три варианта суффикса) ----
def test_source_product_id_basic():
    url = f"{BASE}/shiny/pirelli/scorpion-verde/s-215-55-18-v-99-no-spike-id-52705-s.html"
    assert source_product_id_from_url(url) == "52705"


def test_source_product_id_kamera():
    url = f"{BASE}/shiny/cordiant/vs-5/s-235-75-15-t-105-no-spike-id-52673-kamera-s.html"
    assert source_product_id_from_url(url) == "52673"


def test_source_product_id_long_suffix():
    url = (
        f"{BASE}/shiny/carleo/gle-2/"
        "s-425-85-21-c-167-no-spike-id-144655-kamera-lenta-sloi-22-s.html"
    )
    assert source_product_id_from_url(url) == "144655"


# ---- 4. Шипы из URL ----
def test_studded_from_url():
    spike_url = f"{BASE}/shiny/kama/503-ent/s-135-80-12-q-68-spike-id-62594-s.html"
    no_spike_url = f"{BASE}/shiny/pirelli/scorpion-verde/s-215-55-18-v-99-no-spike-id-52705-s.html"
    assert detect_studded_from_url(spike_url) is True
    assert detect_studded_from_url(no_spike_url) is False


# ---- 5. Блок атрибутов (Ширина/Профиль/Диаметр/Сезон/Бренд + speed upper) ----
_PIRELLI_HTML = """
<html><body>
<h1>Pirelli Scorpion Verde 215/55 R18</h1>
<div class="_parameter">
  <ul>
    <li><span>Размер:</span><span><a class="link">215/55 R18</a></span></li>
    <li><span>Ширина:</span><span>215</span></li>
    <li><span>Профиль:</span><span>55</span></li>
    <li><span>Диаметр:</span><span>18</span></li>
    <li><span>Сезон:</span><span><a class="link">Летние</a></span></li>
    <li><span>Бренд:</span><span itemprop="brand"><a>Pirelli</a></span></li>
    <li><span>Название:</span><span itemprop="model"><a>Scorpion Verde</a></span></li>
    <li><span>Индекс нагрузки:</span><span>99 — до 775 кг</span></li>
    <li><span>Индекс скорости:</span><span>v — до 240 км/ч</span></li>
    <li><span>Артикул:</span><span itemprop="sku">20022</span></li>
  </ul>
</div>
<div class="product_cart_price"><span itemprop="price" content="50900">50 900</span> <span class="priceCurrency">тг</span></div>
<a class="fancybox" href="/media/product/abc_full.png"><img src="/media/product/abc_320x320.png"></a>
</body></html>
"""

_PIRELLI_URL = (
    f"{BASE}/shiny/pirelli/scorpion-verde/s-215-55-18-v-99-no-spike-id-52705-s.html"
)


def test_attribute_block():
    p = _page(_PIRELLI_URL, _PIRELLI_HTML)
    assert p is not None
    a = p.attributes
    assert a["tire_width"] == 215
    assert a["tire_profile"] == 55
    assert a["tire_diameter"] == 18
    assert a["season"] == "Летняя"        # detect_season('Летние') -> Летняя
    assert a["load_index"] == "99"
    assert a["speed_index"] == "V"        # .upper() из «v — ...»
    assert p.brand == "Pirelli"
    assert p.article_sku == "20022"
    assert p.source_product_id == "52705"


# ---- 6. Цена (формат «50 900 тг») ----
def test_price_parse():
    p = _page(_PIRELLI_URL, _PIRELLI_HTML)
    assert p is not None
    assert p.offers[0].price == 50900.0
    assert p.offers[0].currency == "KZT"
    # Картинка — _full из /media/product/
    assert p.image_url == f"{BASE}/media/product/abc_full.png"


# ---- 7. Доступность: out-of-stock карточка (цены нет => «Под заказ») ----
# Реальный кейс altraauto: у out-of-stock товаров <meta itemprop="price" content="0">,
# наличие «нулевое». На сайте действительно так — цена и наличие коррелируют:
# нет цены => «Под заказ».
_BACKORDER_HTML = """
<html><body>
<h1>CARLEO GLE-2 425/85 R21 PR22</h1>
<div class="_parameter"><ul>
  <li><span>Ширина сечения:</span><span>425</span></li>
  <li><span>Профиль:</span><span>85</span></li>
  <li><span>Диаметр:</span><span>21</span></li>
  <li><span>Бренд:</span><span>CARLEO</span></li>
</ul></div>
<meta itemprop="price" content="0"/>
<p>Товара нет в наличии</p>
</body></html>
"""


def test_availability_under_order():
    url = (
        f"{BASE}/shiny/carleo/gle-2/"
        "s-425-85-21-c-167-no-spike-id-144655-kamera-lenta-sloi-22-s.html"
    )
    p = _page(url, _BACKORDER_HTML)
    assert p is not None
    assert p.offers[0].availability == "Под заказ"
    assert p.offers[0].price is None


# ---- 8. Доступность: «В наличии» (нет «На заказ») ----
_IN_STOCK_HTML = """
<html><body>
<h1>Yokohama Ice Guard IG50+ 225/50 R17</h1>
<div class="_parameter"><ul>
  <li><span>Ширина:</span><span>225</span></li>
  <li><span>Профиль:</span><span>50</span></li>
  <li><span>Диаметр:</span><span>17</span></li>
  <li><span>Сезон:</span><span>Зимние</span></li>
  <li><span>Бренд:</span><span>Yokohama</span></li>
  <li><span>Индекс нагрузки:</span><span>94 — до 670 кг</span></li>
  <li><span>Индекс скорости:</span><span>Q — до 160 км/ч</span></li>
  <li><span>Артикул:</span><span>70156</span></li>
</ul></div>
<div class="product_cart_price"><span itemprop="price">45 000</span> тг</div>
<div class="available">В наличии: 4 шт.</div>
</body></html>
"""


def test_availability_in_stock():
    url = f"{BASE}/shiny/yokohama/ice-guard-ig50-plus/s-225-50-17-q-94-no-spike-id-63288-s.html"
    p = _page(url, _IN_STOCK_HTML)
    assert p is not None
    assert p.offers[0].availability == "В наличии"
    assert p.offers[0].quantity_in_stock == 4   # «В наличии: 4 шт.» -> int 4
    assert p.offers[0].price == 45000.0
    # Зимняя без шипов (URL: no-spike), runflat не упомянут в имени
    assert p.attributes["studded"] is False
    assert p.attributes["season"] == "Зимняя"


# ---- 9. Regression: на странице ДВА блока (активный + неактивный «На заказ 0 шт.») ----
# Это реальный кейс altraauto — без активного приоритета мы бы поставили «Под заказ»
# из-за "На заказ 0 шт." в неактивном блоке (баг, который чиним).
_DUAL_BLOCK_HTML = """
<html><body>
<h1>Pirelli Scorpion Verde 215/55 R18</h1>
<div class="_parameter"><ul>
  <li><span>Ширина:</span><span>215</span></li>
  <li><span>Профиль:</span><span>55</span></li>
  <li><span>Диаметр:</span><span>18</span></li>
  <li><span>Сезон:</span><span>Летние</span></li>
  <li><span>Бренд:</span><span>Pirelli</span></li>
</ul></div>
<span itemprop="price" content="50900">50 900</span>
<div class="_product_cart_row" data-product-block-type="local">
  С доставкой 3 шт. Срок доставки — от 3 до 4 дней. 50 900 тг
</div>
<div class="_product_cart_row _inactive" data-product-block-type="warehouse">
  На заказ 0 шт. (от 4 дней)
</div>
</body></html>
"""


def test_active_block_wins_over_inactive_warehouse():
    p = _page(_PIRELLI_URL, _DUAL_BLOCK_HTML)
    assert p is not None
    # Активный «local» блок -> «В наличии», qty=3.
    # Игнорируем «На заказ 0 шт.» в _inactive (это был реальный баг сэмпла).
    assert p.offers[0].availability == "В наличии"
    assert p.offers[0].quantity_in_stock == 3
    assert p.offers[0].price == 50900.0      # itemprop="price" content -> точное число


def test_price_zero_skipped():
    # У карточки в HTML «доставка 0 тг» раньше попадала в price (баг). Должно быть None.
    html = """
    <html><body>
    <h1>Test</h1>
    <div class="_parameter"><ul>
      <li><span>Бренд:</span><span>Test</span></li>
    </ul></div>
    <p>Доставка 0 тг</p>
    </body></html>
    """
    p = _page(_PIRELLI_URL, html)
    assert p is not None
    assert p.offers[0].price is None     # 0 тг отбрасываем (это не цена товара)


# ---- 10. Regression: out-of-stock — <meta content="0"> + блок «Товара нет в наличии» +
# «активные» _product_cart_row (доставка). Раньше парсер видел активные блоки и
# ставил «В наличии». Должно быть «Под заказ», price=None.
_OOS_HTML = """
<html><body>
<h1>Triangle TH201 215/55 R17</h1>
<div class="_parameter"><ul>
  <li><span>Ширина:</span><span>215</span></li>
  <li><span>Профиль:</span><span>55</span></li>
  <li><span>Диаметр:</span><span>17</span></li>
  <li><span>Сезон:</span><span>Летние</span></li>
  <li><span>Бренд:</span><span>Triangle</span></li>
</ul></div>
<meta itemprop="price" content="0"/>
<div class="_product_cart_row">Товара нет в наличии Посмотреть аналогичные товары</div>
<div class="_product_cart_row _inactive">0 тг На заказ 0 шт. (от -1 дней)</div>
<div class="_product_cart_row _product_cart_delivery-info">Срок доставки — -1 день Стоимость доставки — 5000 тг</div>
</body></html>
"""


def test_out_of_stock_with_active_delivery_block():
    url = f"{BASE}/shiny/triangle/th201/s-215-55-17-y-94-no-spike-id-78922-s.html"
    p = _page(url, _OOS_HTML)
    assert p is not None
    # Цена 0 -> None; «активные» блоки доставки не должны давать «В наличии».
    assert p.offers[0].price is None
    assert p.offers[0].availability == "Под заказ"
    assert p.offers[0].quantity_in_stock is None
