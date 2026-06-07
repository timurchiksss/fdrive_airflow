"""Тесты longest-match robots.txt. Запуск: pytest -q"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freedom_parser.common.robots import RobotsRules

UA = "FreedomHolding-SDU-Catalog-Bot/1.0 (+research)"

CARCITY = """User-agent: *
Disallow: /
Allow: /$
Allow: /catalog
Allow: /category/
Allow: /product/
Sitemap: https://carcity.kz/sitemap_index.xml
"""

PITSTOP = """User-agent: *
Disallow: /catalog/view/javascript/hide

User-agent: SemrushBot
Disallow: /
"""

EMPTY = """User-agent: *
Disallow:
"""


class TestCarcity:
    def test_product_and_category_allowed(self):
        r = RobotsRules.parse(CARCITY, UA)
        assert r.allowed("https://carcity.kz/product/triangle-1088307") is True
        assert r.allowed("https://carcity.kz/category/siny-letnie?page=1") is True
        assert r.allowed("https://carcity.kz/catalog") is True

    def test_root_only_allowed_exact(self):
        r = RobotsRules.parse(CARCITY, UA)
        assert r.allowed("https://carcity.kz/") is True       # /$
        assert r.allowed("https://carcity.kz/cart") is False  # совпадает только Disallow: /


class TestPitstop:
    def test_catalog_allowed(self):
        r = RobotsRules.parse(PITSTOP, UA)
        assert r.allowed("https://pitstopshop.kz/catalog/tyre/") is True

    def test_hidden_js_blocked(self):
        r = RobotsRules.parse(PITSTOP, UA)
        assert r.allowed("https://pitstopshop.kz/catalog/view/javascript/hide") is False

    def test_semrush_group_not_applied_to_us(self):
        r = RobotsRules.parse(PITSTOP, UA)
        # Правило Disallow:/ относится к SemrushBot, не к нам.
        assert r.allowed("https://pitstopshop.kz/anything") is True


class TestEmpty:
    def test_all_allowed(self):
        r = RobotsRules.parse(EMPTY, UA)
        assert r.allowed("https://example.kz/whatever") is True
