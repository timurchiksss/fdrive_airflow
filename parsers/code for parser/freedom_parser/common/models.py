"""Доменные модели и канонический порядок колонок широкого CSV.

Структура соответствует модели мастер-каталога из SDU_edited.pdf:
- Product   ~ строка skus + sku_source_mapping + sku_attribute_values
- Offer     ~ строка sku_price_history (цена/наличие/остаток у конкретного продавца)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

# Группы категорий мастер-каталога.
CATEGORY_GROUPS = ("tires", "oils", "filters", "batteries")

# Атрибуты по категориям (PDF §4 — минимум; плюс всё, что отдаёт сайт).
ATTRS_BY_GROUP: dict[str, list[str]] = {
    "tires": [
        "tire_width", "tire_profile", "tire_diameter", "season",
        "load_index", "speed_index", "runflat", "studded",
        "model_name", "tire_type", "tread_pattern", "offroad_marking",
        "set_configuration", "brand_country", "reinforced",
    ],
    "oils": [
        "viscosity", "volume_liters", "oil_type", "engine_type",
        "specification", "product_line", "package_type",
        "atf_standard", "transmission_type", "hypoid",
    ],
    "batteries": [
        "capacity_ah", "voltage_v", "start_current_a", "polarity",
        "battery_type", "dimensions", "terminal_type", "case_type",
    ],
    "filters": [
        "filter_type", "manufacturer_article",
    ],
}

# Кросс-категорийные атрибуты (есть во всех таблицах, заполняются где есть данные).
CROSS_ATTRS = [
    "purpose", "features", "weight",
    "compatible_brand", "compatible_model", "compatible_years",
]

# Идентификация товара.
IDENTITY_COLUMNS = [
    "source", "source_product_id", "source_url",
    "category_group", "category_l1", "category_leaf",
    "name", "brand", "article_sku", "oem_numbers", "image_url", "parsed_at",
]

# Поля предложения (по строке на продавца — мультипродавец).
OFFER_COLUMNS = [
    "seller_name", "price", "old_price", "currency", "availability",
    "quantity_in_stock", "delivery_days", "city",
]

# Все атрибутные колонки (кросс + по категориям, без дублей, в фикс. порядке).
ATTR_COLUMNS = CROSS_ATTRS + [c for g in CATEGORY_GROUPS for c in ATTRS_BY_GROUP[g]]

# «Паспорт» — общие колонки в каждой из 4 таблиц (для split_by_category).
COMMON_COLUMNS = IDENTITY_COLUMNS + OFFER_COLUMNS + CROSS_ATTRS

# Итоговый порядок колонок широкого CSV.
CSV_COLUMNS = IDENTITY_COLUMNS + OFFER_COLUMNS + ATTR_COLUMNS

# Соответствие имён колонок raw -> канон атрибута из ТЗ (PDF §4).
ATTRIBUTE_CANON = {
    "tire_width": "width",
    "tire_profile": "profile",
    "tire_diameter": "diameter",
    "oem_numbers": "oem_number",
}


@dataclass
class Offer:
    """Предложение продавца: цена/наличие/остаток. Несколько на товар = мультипродавец."""
    seller_name: str = ""
    price: float | None = None
    old_price: float | None = None
    currency: str = "KZT"
    availability: str = ""
    quantity_in_stock: int | None = None
    delivery_days: int | None = None
    city: str = ""


@dataclass
class Product:
    """Один товар-источник со всеми предложениями и атрибутами."""
    source: str
    source_product_id: str
    source_url: str
    name: str = ""
    brand: str = ""
    article_sku: str = ""
    category_group: str = ""        # одна из CATEGORY_GROUPS
    category_l1: str = ""           # верхняя категория
    category_leaf: str = ""         # листовая категория
    oem_numbers: list[str] = field(default_factory=list)
    image_url: str = ""
    attributes: dict[str, object] = field(default_factory=dict)  # ключи из ATTR_COLUMNS
    offers: list[Offer] = field(default_factory=list)
    parsed_at: str = ""

    def fingerprint(self) -> str:
        """Хэш значимых полей для детекта изменений (инкрементальность)."""
        import hashlib

        payload = {
            "name": self.name,
            "brand": self.brand,
            "attributes": {k: self.attributes.get(k) for k in sorted(self.attributes)},
            "offers": sorted(
                (o.seller_name, o.price, o.old_price, o.availability)
                for o in self.offers
            ),
        }
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_rows(self) -> list[dict]:
        """Разворачивает товар в строки CSV: одна строка на предложение продавца."""
        base = {
            "source": self.source,
            "source_product_id": self.source_product_id,
            "source_url": self.source_url,
            "category_group": self.category_group,
            "category_l1": self.category_l1,
            "category_leaf": self.category_leaf,
            "name": self.name,
            "brand": self.brand,
            "article_sku": self.article_sku,
            "oem_numbers": "; ".join(self.oem_numbers) if self.oem_numbers else "",
            "image_url": self.image_url,
            "parsed_at": self.parsed_at,
        }
        for key in ATTR_COLUMNS:
            base[key] = self.attributes.get(key, "")

        offers = self.offers or [Offer(currency="KZT")]
        rows = []
        for offer in offers:
            row = dict(base)
            row.update({
                "seller_name": offer.seller_name,
                "price": offer.price if offer.price is not None else "",
                "old_price": offer.old_price if offer.old_price is not None else "",
                "currency": offer.currency,
                "availability": offer.availability,
                "quantity_in_stock": offer.quantity_in_stock
                if offer.quantity_in_stock is not None else "",
                "delivery_days": offer.delivery_days
                if offer.delivery_days is not None else "",
                "city": offer.city,
            })
            rows.append(row)
        return rows
