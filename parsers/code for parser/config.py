"""Конфигурация парсера Freedom Master Data Catalog (часть Nuradil Abyz).

Здесь собраны все настройки, которые меняются между запусками или сайтами:
пути вывода, вежливость (rate limit / число воркеров), User-Agent и описания
сайтов с целевыми категориями.
"""
from __future__ import annotations

from pathlib import Path

# --- Пути ---
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PARSER_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
STATE_DB = DATA_DIR / "state.sqlite"  # legacy-дефолт; реально используем site_dir()/state.sqlite


def site_dir(site: str) -> Path:
    """Папка результатов конкретного сайта: data/<site>/ (каждый парсинг — отдельно)."""
    d = DATA_DIR / site
    d.mkdir(parents=True, exist_ok=True)
    return d

# --- Сетевые настройки / вежливость ---
# Честный User-Agent: парсинг для учебно-производственного проекта Freedom x SDU.
USER_AGENT = "FreedomHolding-SDU-Catalog-Bot/1.0 (+master-data-catalog research)"
REQUEST_TIMEOUT = 30          # сек на запрос
MAX_RETRIES = 4               # ретраи на сетевые ошибки / 5xx
DEFAULT_MIN_DELAY = 0.3       # минимальная пауза между запросами к одному хосту, сек
DEFAULT_WORKERS = 6           # число потоков для карточек товаров
RESPECT_ROBOTS = True         # уважать robots.txt (Disallow / Crawl-delay)

# Валюта по умолчанию (оба сайта — Казахстан, тенге).
DEFAULT_CURRENCY = "KZT"

# --- car-city ---
# Рабочий домен без дефиса (car-city.kz — алиас того же приложения).
CARCITY_BASE = "https://carcity.kz"
# Sitemap-индекс категорий на S3 (для справки/ручной ревизии списка ниже).
CARCITY_CATEGORY_SITEMAP = (
    "https://carscity-s3-prod.object.pscloud.io/sitemap/category.xml"
)

# Явный allowlist целевых категорий car-city (slug в /category/<slug>).
# Курируется вручную — список «будет обновляться со временем» (см. ТЗ).
# Порядок важен для шин: сезонные категории идут ПЕРЕД зонтичной "siny",
# чтобы товар получил сезон из своей категории (дедуп — по id товара).
# Намеренно НЕ включены смежные не-товарные разделы: диски, маслосъёмные
# колпачки, съёмники фильтров, зарядные устройства/аксессуары для АКБ и т.п.
CARCITY_CATEGORIES: dict[str, list[str]] = {
    "tires": [
        "siny-letnie",
        "siny-zimnie",
        "siny-dlia-kommerceskogo-transporta",
        "siny-dlia-gruzovogo-transporta",
        "motosiny",
        "siny",  # зонтичная — добирает всесезонные/прочие, идёт последней
    ],
    "oils": [
        "motornye-masla",
        "avtomobilnye-motornye-masla",
        "motornye-masla-dlia-mototexniki",
        "motornye-masla-dlia-lodocnyx-motorov",
        "transmissionnye-masla",
        "specialnye-masla",
    ],
    "filters": [
        "maslianye-filtry",
        "vozdusnye-filtry",
        "salonnye-filtry",
        "toplivnye-filtry",
        "transmissionnye-filtry",
        "gidravliceskie-filtry",
    ],
    "batteries": [
        "akkumuliatornye-batarei",
    ],
}
CARCITY_PER_PAGE = 500

# --- pitstopshop ---
PITSTOP_BASE = "https://pitstopshop.kz"
PITSTOP_SITEMAP = "https://pitstopshop.kz/sitemap.xml"
# Корневые разделы каталога шин. По умолчанию только легковые (tyre).
PITSTOP_TYRE_ROOTS = {
    "tyre": "/catalog/tyre/",   # легковые (по умолчанию)
    "gruz": "/catalog/gruz/",   # грузовые (опц.)
    "moto": "/catalog/moto/",   # мото (опц.)
    "atv": "/catalog/atv/",     # квадроциклы (опц.)
    "sh": "/catalog/sh/",       # сельхоз (опц.)
}
PITSTOP_DEFAULT_ROOTS = ["tyre"]

# --- altraauto ---
ALTRAAUTO_BASE = "https://altraauto.kz"
ALTRAAUTO_SITEMAP_INDEX = ALTRAAUTO_BASE + "/sitemap-index.xml"

# --- expertoil ---
EXPERTOIL_BASE = "https://www.expertoil.kz"
EXPERTOIL_OILS_LISTING = EXPERTOIL_BASE + "/ru/catalog/masla_490/"
EXPERTOIL_BATTERIES_LISTING = EXPERTOIL_BASE + "/ru/catalog/akkumulyatory_490/"
