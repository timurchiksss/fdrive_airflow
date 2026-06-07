"""Определение группы категории мастер-каталога по slug/тексту.

Группы: tires / oils / filters / batteries (см. models.CATEGORY_GROUPS).
car-city использует транслит-slug (siny, masla, filtry, akkum...),
а хлебные крошки — кириллицу (Шины, Масла, ...). Обрабатываем оба варианта.
"""
from __future__ import annotations

# Ключевые слова по группам: и транслит (из slug), и кириллица (из текста).
# Порядок важен: фильтры проверяем раньше масел, т.к. "масляный фильтр".
_GROUP_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("filters", ("filtr", "фильтр")),
    ("tires", ("siny", "shin", "шин", "покрышк")),
    ("batteries", ("akkum", "akb", "аккум", "акб")),
    ("oils", ("masla", "maslo", "масл", "avtoximi", "автохими")),
]

# Целевые группы car-city (все 4) и человекочитаемые названия L1.
CARCITY_TARGET_GROUPS = ("tires", "oils", "filters", "batteries")

GROUP_L1_NAME = {
    "tires": "Шины",
    "oils": "Масла",
    "filters": "Фильтры",
    "batteries": "Аккумуляторы",
}


def classify(text: str) -> str | None:
    """Вернуть группу категории по slug или тексту, либо None если не целевая."""
    if not text:
        return None
    low = text.lower()
    for group, keywords in _GROUP_KEYWORDS:
        if any(kw in low for kw in keywords):
            return group
    return None


def is_target_carcity_category(slug_or_text: str) -> bool:
    """True, если категория car-city относится к одной из 4 целевых групп."""
    return classify(slug_or_text) in CARCITY_TARGET_GROUPS
