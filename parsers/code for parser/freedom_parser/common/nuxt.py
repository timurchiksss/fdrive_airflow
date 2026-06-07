"""Разбор встроенного состояния Nuxt (`__NUXT_DATA__`) car-city.

car-city отдаёт данные товара в devalue-сериализованном массиве: значения
ссылаются друг на друга по индексу. Здесь — минимально нужное:

- `parse_nuxt_data` — достать массив из HTML;
- `deref` — резолвить ссылку-индекс (с защитой от циклов);
- `find_offers` — ВСЕ предложения продавцов (мультипродавец, приоритет №1);
- `characteristics` — все характеристики товара (одно- и МНОГО-значные), напр.
  «Год выпуска автомобиля» → ['1997','1998'].
"""
from __future__ import annotations

import json
import re

_NUXT_RE = re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)

# "Имя характеристики", <ref:int>, [<индексы значений>], "значение1"[, "значение2", ...]
_CHAR_RE = re.compile(
    r'"([^"\\]{2,40})"\s*,\s*\d+\s*,\s*\[([\d,\s]*)\]'
    r'((?:\s*,\s*"[^"\\]{0,90}")+)'
)
_QUOTED = re.compile(r'"([^"\\]{0,90})"')


def parse_nuxt_data(html: str) -> list:
    m = _NUXT_RE.search(html or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def deref(arr: list, i, _depth: int = 0, _seen: tuple = ()):
    """Резолвить значение по индексу devalue (dict/list/scalar)."""
    if not isinstance(i, int) or i < 0 or i >= len(arr) or i in _seen or _depth > 6:
        return i
    v = arr[i]
    _seen = _seen + (i,)
    if isinstance(v, dict):
        return {k: deref(arr, x, _depth + 1, _seen) for k, x in v.items()}
    if isinstance(v, list):
        return [deref(arr, x, _depth + 1, _seen) for x in v[:20]]
    return v


def find_offers(arr: list) -> list[dict]:
    """Все предложения продавцов: [{seller, price, delivery_days, preorder, quantity_in_stock}].

    Дедуплицируются по (seller, price).
    """
    out: list[dict] = []
    seen: set = set()
    for el in arr:
        if not (isinstance(el, dict) and "company" in el and "price" in el
                and "quantity_in_stock" in el):
            continue
        o = {k: deref(arr, v) for k, v in el.items()}
        comp = o.get("company")
        seller = comp.get("name") if isinstance(comp, dict) else comp
        price = o.get("price")
        per_unit = price.get("per_unit") if isinstance(price, dict) else price
        if not seller:
            continue
        key = (seller, per_unit)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "seller": seller,
            "price": per_unit,
            "delivery_days": o.get("delivery_days"),
            "preorder": o.get("preorder"),
            "quantity_in_stock": o.get("quantity_in_stock"),
        })
    return out


_PHYS_KEYS = ("weight", "length", "width", "height")


def physical_fields(arr: list, name: str | None = None) -> dict[str, int | float]:
    """Физ-параметры из ТОВАРНОГО узла payload: вес (г) и габариты (мм).

    Эти поля лежат не в массиве характеристик, а в самом узле товара
    (рядом `offers`/`slug`/`attributes`). Возвращаем только положительные
    значения (0 = не задано на сайте). `name` (из JSON-LD) уточняет выбор
    нужного узла среди возможных (связанные/рекомендованные товары).
    """
    best = None
    best_score = -1
    for el in arr:
        if not (isinstance(el, dict) and "offers" in el and "slug" in el
                and all(k in el for k in _PHYS_KEYS)):
            continue
        score = len(el)  # главный товар — самый «богатый» узел
        if name is not None:
            nm = deref(arr, el.get("name"))
            if isinstance(nm, str) and nm.strip() == name.strip():
                score += 10_000
        if score > best_score:
            best_score = score
            best = el
    if best is None:
        return {}
    out: dict[str, int | float] = {}
    for k in _PHYS_KEYS:
        val = deref(arr, best.get(k))
        if isinstance(val, bool):
            continue
        if isinstance(val, (int, float)) and val > 0:
            out[k] = int(val) if float(val).is_integer() else val
    return out


def characteristics(html: str) -> dict[str, list[str]]:
    """Все характеристики товара: имя -> список значений (1 или несколько)."""
    out: dict[str, list[str]] = {}
    for m in _CHAR_RE.finditer(html or ""):
        name = m.group(1)
        idxs = [x for x in m.group(2).split(",") if x.strip()]
        count = max(1, len(idxs))
        values = _QUOTED.findall(m.group(3))[:count]
        values = [v for v in values if v != ""]
        if values and name not in out:
            out[name] = values
    return out
