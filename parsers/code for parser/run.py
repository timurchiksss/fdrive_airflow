#!/usr/bin/env python3
"""CLI парсера автотоваров (часть Nuradil Abyz: car-city + pitstopshop).

Примеры:
  python run.py --site carcity --categories all
  python run.py --site carcity --categories tires,oils --limit 50
  python run.py --site pitstopshop --roots tyre
  python run.py --site all --workers 8

Результат:
  data/<site>_products.csv        — широкий снимок (1 строка на товар×предложение)
  data/<site>_price_history.csv   — append-лог истории цен (новые/изменившиеся)
  data/state.sqlite               — состояние для инкрементальных прогонов
"""
from __future__ import annotations

import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from freedom_parser.common.http import Fetcher
from freedom_parser.common.models import CATEGORY_GROUPS, Product
from freedom_parser.common.state import State
from freedom_parser.common.storage import PriceHistoryWriter, WideCsvWriter
from freedom_parser.sites.altraauto import AltraautoScraper
from freedom_parser.sites.carcity import CarCityScraper
from freedom_parser.sites.expertoil import ExpertoilScraper
from freedom_parser.sites.pitstopshop import PitStopShopScraper

log = logging.getLogger("freedom_parser.run")

# Алиасы названий категорий -> группы мастер-каталога.
_GROUP_ALIASES = {
    "tires": "tires", "шины": "tires", "шина": "tires", "tyre": "tires",
    "oils": "oils", "масла": "oils", "масло": "oils", "oil": "oils",
    "filters": "filters", "фильтры": "filters", "фильтр": "filters", "filter": "filters",
    "batteries": "batteries", "акб": "batteries", "аккумуляторы": "batteries", "battery": "batteries",
}


def _parse_groups(value: str) -> set[str]:
    if not value or value.strip().lower() == "all":
        return set(CATEGORY_GROUPS)
    groups = set()
    for token in value.split(","):
        key = token.strip().lower()
        if key in _GROUP_ALIASES:
            groups.add(_GROUP_ALIASES[key])
        else:
            raise SystemExit(f"Неизвестная категория: {token!r}")
    return groups


def _as_products(result) -> list[Product]:
    if result is None:
        return []
    return result if isinstance(result, list) else [result]


def run_site(site: str, args) -> None:
    fetcher = Fetcher(min_delay=args.min_delay, respect_robots=not args.no_robots)

    if site == "carcity":
        scraper = CarCityScraper(fetcher)
        groups = _parse_groups(args.categories)
        log.info("car-city: обнаружение товаров (категории: %s)…", ", ".join(sorted(groups)))
        items = scraper.discover(groups, limit=args.limit, per_group=args.per_group)
    elif site == "pitstopshop":
        scraper = PitStopShopScraper(fetcher)
        roots = [r.strip() for r in args.roots.split(",")] if args.roots else config.PITSTOP_DEFAULT_ROOTS
        log.info("pitstopshop: обнаружение моделей (разделы: %s)…", ", ".join(roots))
        items = scraper.discover(roots, limit=args.limit)
    elif site == "altraauto":
        scraper = AltraautoScraper(fetcher)
        log.info("altraauto: обнаружение карточек шин (sitemap-index)…")
        items = scraper.discover(limit=args.limit)
    elif site == "expertoil":
        scraper = ExpertoilScraper(fetcher)
        log.info("expertoil: обнаружение карточек (масла + АКБ)…")
        items = scraper.discover(limit=args.limit)
    else:
        raise SystemExit(f"Неизвестный сайт: {site}")

    out_dir = config.site_dir(site)                      # data/<site>/ — отдельная папка
    products_path = out_dir / f"{site}_products.csv"
    history_path = out_dir / f"{site}_price_history.csv"

    t0 = time.monotonic()
    n_products = 0
    skipped = 0
    # По умолчанию у каждого сайта свой state -> сайты можно гнать параллельно.
    state = State(args.state or (out_dir / "state.sqlite"))
    if args.resume:
        done_keys = state.done_items(site)
        before = len(items)
        items = [it for it in items if it[0] not in done_keys]
        skipped = before - len(items)
        log.info("%s: resume — пропускаю %d уже собранных, к разбору %d", site, skipped, len(items))
    else:
        state.clear_items(site)  # свежий снимок — сбрасываем учёт страниц
        log.info("%s: к разбору %d страниц", site, len(items))

    with WideCsvWriter(products_path, append=args.resume) as csv_out, \
            PriceHistoryWriter(history_path) as hist_out, state:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(scraper.parse, *item): item for item in items}
            for done, fut in enumerate(as_completed(futures), 1):
                item = futures[fut]
                try:
                    products = _as_products(fut.result())
                except Exception as exc:  # noqa: BLE001 — не валим весь прогон из-за одной страницы
                    log.warning("ошибка разбора %s: %s", item[0], exc)
                    continue
                for product in products:
                    csv_out.write(product)
                    status = state.record(product)
                    if status in ("new", "changed"):
                        hist_out.write(product)
                    n_products += 1
                state.mark_item_done(site, item[0])
                if done % 200 == 0:
                    log.info("%s: %d/%d страниц | товаров %d | время %.0fc",
                             site, done, len(items), n_products, time.monotonic() - t0)
                    state.commit()

        st = state.stats

    dt = time.monotonic() - t0
    print(f"\n=== {site} ===")
    if skipped:
        print(f"  пропущено (resume): {skipped}")
    print(f"  страниц разобрано : {len(items)}")
    print(f"  товаров           : {n_products}")
    print(f"  строк в CSV        : {csv_out.rows_written}  -> {products_path}")
    print(f"  новые/изменён/без изм: {st['new']}/{st['changed']}/{st['unchanged']}")
    print(f"  строк в истории цен: {hist_out.rows_written}  -> {history_path}")
    print(f"  время             : {dt:.1f} c")


def main() -> None:
    ap = argparse.ArgumentParser(description="Парсер car-city / pitstopshop")
    ap.add_argument("--site", choices=["carcity", "pitstopshop", "altraauto", "expertoil", "all"], required=True)
    ap.add_argument("--categories", default="all",
                    help="car-city: all | tires,oils,filters,batteries")
    ap.add_argument("--roots", default="",
                    help="pitstopshop: tyre[,gruz,moto,atv,sh] (по умолчанию tyre)")
    ap.add_argument("--limit", type=int, default=None,
                    help="ограничить общее число страниц discovery (для теста)")
    ap.add_argument("--per-group", type=int, default=None,
                    help="car-city: не более N товаров на категорию (сбалансированная выборка)")
    ap.add_argument("--workers", type=int, default=config.DEFAULT_WORKERS)
    ap.add_argument("--min-delay", type=float, default=config.DEFAULT_MIN_DELAY,
                    help="мин. пауза между запросами к одному хосту, сек")
    ap.add_argument("--resume", action="store_true",
                    help="продолжить прерванный полный сбор: пропустить уже собранные "
                         "страницы (из state.sqlite) и дописывать в существующий CSV")
    ap.add_argument("--state", default=None,
                    help="путь к state.sqlite (по умолчанию data/<site>/state.sqlite — "
                         "у каждого сайта свой, сайты можно гнать параллельно)")
    ap.add_argument("--no-robots", action="store_true",
                    help="не проверять robots.txt (не рекомендуется)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    sites = ["carcity", "pitstopshop", "altraauto", "expertoil"] if args.site == "all" else [args.site]
    for site in sites:
        run_site(site, args)


if __name__ == "__main__":
    main()
