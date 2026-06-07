"""Запись результатов: широкий CSV (снимок) + append-лог истории цен."""
from __future__ import annotations

import csv
from pathlib import Path

from freedom_parser.common.models import CSV_COLUMNS, Product

PRICE_HISTORY_COLUMNS = [
    "parsed_at", "price_date", "source", "source_product_id",
    "seller_name", "city", "price", "old_price", "discount_price",
    "currency", "availability",
]


class WideCsvWriter:
    """Широкий CSV: одна строка на (товар × предложение). Перезаписывается."""

    def __init__(self, path: str | Path, append: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = append and self.path.exists() and self.path.stat().st_size > 0
        self._fh = self.path.open("a" if existing else "w", newline="", encoding="utf-8-sig")
        self._writer = csv.DictWriter(
            self._fh, fieldnames=CSV_COLUMNS, extrasaction="ignore"
        )
        if not existing:
            self._writer.writeheader()
        self.rows_written = 0

    def write(self, product: Product) -> None:
        for row in product.to_rows():
            self._writer.writerow(row)
            self.rows_written += 1

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "WideCsvWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class PriceHistoryWriter:
    """Append-only лог истории цен (по строке на предложение на момент прогона)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists() or self.path.stat().st_size == 0
        self._fh = self.path.open("a", newline="", encoding="utf-8-sig")
        self._writer = csv.DictWriter(
            self._fh, fieldnames=PRICE_HISTORY_COLUMNS, extrasaction="ignore"
        )
        if new_file:
            self._writer.writeheader()
        self.rows_written = 0

    def write(self, product: Product) -> None:
        for offer in product.offers:
            if offer.price is None:
                continue  # размеры «нет в наличии» (без цены) не пишем в историю цен
            self._writer.writerow({
                "parsed_at": product.parsed_at,
                "price_date": product.parsed_at[:10],  # YYYY-MM-DD из ISO-времени
                "source": product.source,
                "source_product_id": product.source_product_id,
                "seller_name": offer.seller_name,
                "city": offer.city,
                "price": offer.price if offer.price is not None else "",
                "old_price": offer.old_price if offer.old_price is not None else "",
                "discount_price": "",  # появится, если у источника будет отдельная акционная цена
                "currency": offer.currency,
                "availability": offer.availability,
            })
            self.rows_written += 1

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "PriceHistoryWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
