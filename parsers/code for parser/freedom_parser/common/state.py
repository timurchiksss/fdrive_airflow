"""Состояние для инкрементальных прогонов (SQLite).

Хранит на каждый (source, source_product_id): отпечаток значимых полей,
first_seen/last_seen. Позволяет классифицировать товар как новый/изменившийся/
без изменений и решить, дописывать ли строку в историю цен.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from freedom_parser.common.models import Product


class State:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                source TEXT NOT NULL,
                source_product_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (source, source_product_id)
            )
        """)
        # Учёт обработанных единиц discovery (URL товара/модели) — для resume.
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS done_items (
                source TEXT NOT NULL,
                item_key TEXT NOT NULL,
                PRIMARY KEY (source, item_key)
            )
        """)
        self._conn.commit()
        self.stats = {"new": 0, "changed": 0, "unchanged": 0}

    # ---- учёт обработанных страниц (resume) ----
    def done_items(self, source: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT item_key FROM done_items WHERE source=?", (source,)
        ).fetchall()
        return {r[0] for r in rows}

    def mark_item_done(self, source: str, item_key: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO done_items VALUES (?,?)", (source, item_key)
        )

    def clear_items(self, source: str) -> None:
        self._conn.execute("DELETE FROM done_items WHERE source=?", (source,))
        self._conn.commit()

    def classify(self, product: Product) -> str:
        """Вернуть 'new' | 'changed' | 'unchanged' (без записи)."""
        row = self._conn.execute(
            "SELECT fingerprint FROM products WHERE source=? AND source_product_id=?",
            (product.source, product.source_product_id),
        ).fetchone()
        if row is None:
            return "new"
        return "unchanged" if row[0] == product.fingerprint() else "changed"

    def record(self, product: Product) -> str:
        """Классифицировать, обновить состояние и вернуть статус."""
        status = self.classify(product)
        fp = product.fingerprint()
        now = product.parsed_at
        if status == "new":
            self._conn.execute(
                "INSERT INTO products VALUES (?,?,?,?,?)",
                (product.source, product.source_product_id, fp, now, now),
            )
        else:
            self._conn.execute(
                "UPDATE products SET fingerprint=?, last_seen=? "
                "WHERE source=? AND source_product_id=?",
                (fp, now, product.source, product.source_product_id),
            )
        self.stats[status] += 1
        return status

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()

    def __enter__(self) -> "State":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
