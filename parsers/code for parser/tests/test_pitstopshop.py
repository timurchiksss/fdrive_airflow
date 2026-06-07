"""Тесты парсера pitstopshop (двухуровневый обход, разбор размеров)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from freedom_parser.sites.pitstopshop import (
    PitStopShopScraper,
    _catalog_segments,
    _map_studded,
    _row_price,
)

BASE = "https://pitstopshop.kz"
MODEL_URL = f"{BASE}/catalog/tyre/maxxis/at-771/"

MODEL_HTML = """
<html><head><meta property="og:image" content="http://img/x.jpg"></head><body>
<h1>Maxxis AT-771 Bravo</h1>
<ul>
  <li><strong>Производитель:</strong> <a href="/catalog/tyre/maxxis/">Maxxis</a> (Тайвань)</li>
  <li><strong>Название модели:</strong> AT-771 Bravo</li>
  <li><strong>Тип автомобиля:</strong> внедорожники и кроссоверы</li>
  <li><strong>Сезонность:</strong> Летняя</li>
  <li><strong>Шипы:</strong> нет</li>
</ul>
<div id="tab-sale"><table><tbody>
  <tr class="line"><td><a href="/catalog/tyre/maxxis/at-771/205-70-15-96-t--/">Maxxis AT-771 Bravo 205/70 R15 96T</a></td><td>205/70 R15 96 T</td><td>70040 т.</td><td><a href="#">Купить</a></td></tr>
  <tr><td><a href="/catalog/tyre/maxxis/at-771/235-75-15-109-s-xl-/">Maxxis AT-771 Bravo 235/75 R15 109S XL 3 шт.</a></td><td>235/75 R15 109 S</td><td>98040 т.</td></tr>
  <tr><td><a href="/catalog/tyre/maxxis/at-771/225-75-16-104-v-xl-rf-/">Maxxis Foo 225/75 R16 104V XL RunFlat</a></td><td>225/75 R16 104 V</td><td>120 000 т.</td></tr>
</tbody></table></div>
<div id="tab-soldout"><table><tbody>
  <tr><td><a href="/catalog/tyre/maxxis/at-771/195-65-15-91-h--/">Maxxis AT-771 Bravo 195/65 R15 91H</a></td><td>195/65 R15 91 H</td></tr>
</tbody></table></div>
</body></html>
"""


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url):
        return _FakeResp(self.pages[url]) if url in self.pages else None


def _parse():
    sc = PitStopShopScraper(_FakeFetcher({MODEL_URL: MODEL_HTML}))
    return sc.parse(MODEL_URL, root="tyre")


# ---- чистые помощники ----
def test_catalog_segments_includes_root():
    assert _catalog_segments(f"{BASE}/catalog/tyre/maxxis/at-771/205-70-15-96-t--/") == \
        ["tyre", "maxxis", "at-771", "205-70-15-96-t--"]


def test_row_price_anchors_on_suffix_not_r15():
    # «R15» не должно стать ценой — берём число перед «т.»
    assert _row_price("Maxxis 205/70 R15 96 T 70040 т. Купить") == 70040.0
    assert _row_price("120 000 т.") == 120000.0
    assert _row_price("нет цены") is None


def test_map_studded():
    assert _map_studded("нет") is False
    assert _map_studded("да") is True
    assert _map_studded("шипованная") is True
    assert _map_studded("") is None


# ---- интеграция parse() ----
def test_parse_counts_and_model_attrs():
    prods = _parse()
    assert len(prods) == 4  # 3 в наличии + 1 нет в наличии
    p = next(x for x in prods if x.source_product_id.endswith("205-70-15-96-t--"))
    assert p.brand == "Maxxis"
    assert p.attributes["brand_country"] == "Тайвань"
    assert p.attributes["model_name"] == "AT-771 Bravo"
    assert p.attributes["tire_type"] == "внедорожники и кроссоверы"
    assert p.attributes["season"] == "Летняя"
    assert p.attributes["studded"] is False
    assert p.image_url == "http://img/x.jpg"


def test_parse_size_and_speed_uppercase():
    p = next(x for x in _parse() if x.source_product_id.endswith("205-70-15-96-t--"))
    a = p.attributes
    assert (a["tire_width"], a["tire_profile"], a["tire_diameter"]) == (205, 70, 15)
    assert a["load_index"] == "96"
    assert a["speed_index"] == "T"            # верхний регистр, не «t»


def test_source_product_id_includes_section():
    p = _parse()[0]
    assert p.source_product_id.startswith("tyre/")  # раздел в id -> уникальность между разделами


def test_reinforced_and_runflat_independent():
    prods = _parse()
    xl = next(x for x in prods if x.source_product_id.endswith("235-75-15-109-s-xl-"))
    assert xl.attributes["reinforced"] == "XL"
    assert xl.attributes["runflat"] is False        # XL ≠ RunFlat
    assert xl.offers[0].quantity_in_stock == 3      # «3 шт.»
    assert "шт" not in xl.name                       # остаток вырезан из имени

    both = next(x for x in prods if x.source_product_id.endswith("225-75-16-104-v-xl-rf-"))
    assert both.attributes["reinforced"] == "XL"
    assert both.attributes["runflat"] is True        # XL И RunFlat одновременно
    assert both.attributes["speed_index"] == "V"


def test_instock_vs_soldout():
    prods = _parse()
    instock = next(x for x in prods if x.source_product_id.endswith("205-70-15-96-t--"))
    assert instock.offers[0].price == 70040.0
    assert instock.offers[0].availability == "В наличии"
    assert instock.offers[0].quantity_in_stock is None  # нет «N шт.» -> пусто, не 0

    soldout = next(x for x in prods if x.source_product_id.endswith("195-65-15-91-h--"))
    assert soldout.offers[0].price is None
    assert soldout.offers[0].availability == "Под заказ"


def test_discover_from_sitemap_filters_models_and_roots():
    # sitemap содержит модели (3 сегмента), бренды (2), размеры (4), не-каталог.
    sitemap = f"""<urlset>
      <url><loc>{BASE}/stati/foo</loc></url>
      <url><loc>{BASE}/catalog/tyre/maxxis/</loc></url>
      <url><loc>{BASE}/catalog/tyre/maxxis/at-771/</loc></url>
      <url><loc>{BASE}/catalog/tyre/maxxis/at-771/205-70-15-96-t--/</loc></url>
      <url><loc>{BASE}/catalog/gruz/kama/nr-201/</loc></url>
    </urlset>"""
    sc = PitStopShopScraper(_FakeFetcher({config.PITSTOP_SITEMAP: sitemap}))
    # только tyre: одна модель (бренд/размер/не-каталог отброшены)
    assert sc.discover(roots=["tyre"]) == [(f"{BASE}/catalog/tyre/maxxis/at-771/", "tyre")]
    # tyre+gruz: две модели, root берётся из URL
    res = sc.discover(roots=["tyre", "gruz"])
    assert (f"{BASE}/catalog/gruz/kama/nr-201/", "gruz") in res
    assert len(res) == 2
