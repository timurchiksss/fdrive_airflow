"""Извлечение нормализованных атрибутов из названий/характеристик товаров.

Чистые функции (без сети) — легко тестируются. Покрыты tests/test_attributes.py.
"""
from __future__ import annotations

import re

# ----------------------------------------------------------------------------
# Цена
# ----------------------------------------------------------------------------
_PRICE_RE = re.compile(r"\d[\d\s ]*\d|\d")


def parse_price(text: str | None) -> float | None:
    """'9 506 ₸' / '59860 т.' / '1 180 000 тг' -> float; иначе None."""
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if not m:
        return None
    digits = re.sub(r"[\s ]", "", m.group(0))
    if not digits.isdigit():
        return None
    return float(digits)


# ----------------------------------------------------------------------------
# Шины
# ----------------------------------------------------------------------------
# 195/65 R16 91V  |  205/55R16  |  385/65 R22.5 160K
_TIRE_RE = re.compile(
    r"(?P<w>\d{3})\s*[/x]\s*(?P<p>\d{2,3})\s*"
    r"[RrZzДд]+\s*"
    r"(?P<d>\d{2}(?:[.,]\d)?)"
    r"(?:\s+(?P<load>\d{2,3})\s*(?P<speed>[A-Za-z]{1,2})\b)?",
    re.IGNORECASE,
)


def parse_tire_size(text: str | None) -> dict:
    """Разобрать типоразмер шины из строки (имени или размера)."""
    empty = {
        "tire_width": None, "tire_profile": None, "tire_diameter": None,
        "load_index": "", "speed_index": "",
    }
    if not text:
        return empty
    m = _TIRE_RE.search(text)
    if not m:
        return empty
    diameter_raw = m.group("d").replace(",", ".")
    diameter = float(diameter_raw)
    if diameter.is_integer():
        diameter = int(diameter)
    return {
        "tire_width": int(m.group("w")),
        "tire_profile": int(m.group("p")),
        "tire_diameter": diameter,
        "load_index": m.group("load") or "",
        "speed_index": (m.group("speed") or "").upper(),
    }


def tire_size_from_pitstop_slug(slug: str | None) -> dict:
    """Размер из slug pitstopshop: '175-65-14-82-t--' -> w/p/d/load/speed."""
    empty = {
        "tire_width": None, "tire_profile": None, "tire_diameter": None,
        "load_index": "", "speed_index": "",
    }
    if not slug:
        return empty
    parts = [p for p in slug.strip("/").rsplit("/", 1)[-1].split("-") if p]
    if len(parts) < 3:
        return empty
    w, p, d = parts[0], parts[1], parts[2]
    if not (w.isdigit() and p.isdigit() and d.replace(".", "", 1).isdigit()):
        return empty
    diameter = float(d)
    if diameter.is_integer():
        diameter = int(diameter)
    load = parts[3] if len(parts) >= 4 and parts[3].isdigit() else ""
    speed = parts[4].upper() if len(parts) >= 5 and parts[4].isalpha() else ""
    return {
        "tire_width": int(w), "tire_profile": int(p), "tire_diameter": diameter,
        "load_index": load, "speed_index": speed,
    }


_SEASON_KEYWORDS = [
    ("Всесезонная", ("всесезон", "vsesezon", "all season", "all-season", "all weather", "a/s")),
    ("Зимняя", ("зимн", "зим", "zimn", "winter", "шип", "ice", "snow", "frost")),
    ("Летняя", ("летн", "letn", "summer")),
]


def detect_season(text: str | None) -> str:
    if not text:
        return ""
    low = text.lower()
    for label, keys in _SEASON_KEYWORDS:
        if any(k in low for k in keys):
            return label
    return ""


# Маркеры RunFlat (короткие — с границами слова, чтобы не ловить подстроки).
_RUNFLAT_RE = re.compile(
    r"(run[\s-]?flat|\brft\b|\brof\b|\bssr\b|\bzp\b|\bdsst\b|\bhrs\b|\brun[\s-]?on[\s-]?flat\b)",
    re.IGNORECASE,
)


def detect_runflat(text: str | None) -> bool:
    if not text:
        return False
    return bool(_RUNFLAT_RE.search(text))


def parse_studded(text: str | None) -> bool | None:
    """Шипы у зимней шины: True (шипованная) / False (нешип/липучка) / None (не указано).

    Негативные маркеры проверяем первыми — «без шипов» содержит «шип».
    """
    if not text:
        return None
    low = text.lower()
    if "без шип" in low or "нешип" in low or "липучк" in low or "фрикцион" in low:
        return False
    if "шип" in low:  # «шипованная», «с шипами», «под шип»
        return True
    return None


# ----------------------------------------------------------------------------
# Масла
# ----------------------------------------------------------------------------
_VISCOSITY_RE = re.compile(r"\b(\d{1,2})\s*[Ww]\s*-?\s*(\d{2})\b")
# Моногрейд: SAE 30 / SAE 20W / 75W-90 трансмиссионные ловит мультигрейд выше.
_VISCOSITY_MONO_RE = re.compile(r"\bSAE\s*(\d{1,3}W?)\b", re.IGNORECASE)


def parse_viscosity(text: str | None) -> str:
    """Вязкость SAE: мультигрейд '5W30'->'5W-30'; моногрейд 'SAE 30'->'SAE 30'."""
    if not text:
        return ""
    m = _VISCOSITY_RE.search(text)
    if m:
        return f"{int(m.group(1))}W-{m.group(2)}"
    mono = _VISCOSITY_MONO_RE.search(text)
    if mono:
        return f"SAE {mono.group(1).upper()}"
    return ""


_ML_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:мл|ml)\b", re.IGNORECASE)
_L_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:литр\w*|л|l)\b", re.IGNORECASE)


def parse_volume_liters(text: str | None) -> float | None:
    """Объём в литрах: '4 л'/'4L'/'1л'/'0,5 л' -> float; '200 мл' -> 0.2."""
    if not text:
        return None
    m = _ML_RE.search(text)
    if m:
        return round(float(m.group(1).replace(",", ".")) / 1000, 4)
    m = _L_RE.search(text)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


_SYN_NAME_RE = re.compile(r"\b(syn|synergie|synth|синт)\b", re.IGNORECASE)


def detect_oil_type(text: str | None) -> str:
    if not text:
        return ""
    low = text.lower()
    # Полусинтетику проверяем раньше синтетики (содержит "синт").
    if "полусинт" in low or "semi" in low:
        return "Полусинтетическое"
    if "гидрокрекинг" in low or "hc-synth" in low or "hydrocrack" in low:
        return "Гидрокрекинговое"
    if "синтет" in low or "synthetic" in low:
        return "Синтетическое"
    if "минерал" in low or "mineral" in low:
        return "Минеральное"
    # Эвристика по имени (Motul 6100 SYNERGIE, Petro-Canada SYN, …): отдельное слово.
    if _SYN_NAME_RE.search(text):
        return "Синтетическое"
    return ""


# ----------------------------------------------------------------------------
# Аккумуляторы (АКБ)
# ----------------------------------------------------------------------------
_CAPACITY_RE = re.compile(r"(\d{2,3})\s*(?:а[·.]?ч|ah|ампер[\s-]?час)", re.IGNORECASE)
# Российский ГОСТ-формат «6СТ-N»: N — ёмкость в Ач (Bars, Kainar).
_CAPACITY_GOST_RE = re.compile(r"6\s*СТ\s*-\s*(\d{2,3})", re.IGNORECASE)
_VOLTAGE_RE = re.compile(r"\b(6|12|24)\s*(?:в|v|вольт)\b", re.IGNORECASE)


def parse_capacity_ah(text: str | None) -> int | None:
    if not text:
        return None
    m = _CAPACITY_RE.search(text) or _CAPACITY_GOST_RE.search(text)
    return int(m.group(1)) if m else None


def parse_voltage_v(text: str | None) -> int | None:
    if not text:
        return None
    m = _VOLTAGE_RE.search(text)
    return int(m.group(1)) if m else None


def detect_battery_polarity(text: str | None) -> str:
    if not text:
        return ""
    low = text.lower()
    if "обратн" in low:
        return "Обратная"
    if "прям" in low:
        return "Прямая"
    # Народное обозначение СНГ: «правый» = плюс справа = обратная; «левый» = прямая.
    if "правый" in low or "правая" in low:
        return "Обратная"
    if "левый" in low or "левая" in low:
        return "Прямая"
    # Графическая нотация (Bars/Kainar): «-+» (минус слева, плюс справа) = обратная;
    # «+-» (плюс слева) = прямая. Ищем как отдельный токен (с пробелом по краю).
    if re.search(r"(?:^|\s)-\+(?:\s|$)", low):
        return "Обратная"
    if re.search(r"(?:^|\s)\+-(?:\s|$)", low):
        return "Прямая"
    return ""


# ----------------------------------------------------------------------------
# Фильтры
# ----------------------------------------------------------------------------
def detect_filter_type(text: str | None) -> str:
    if not text:
        return ""
    low = text.lower()
    if "масл" in low:
        return "Масляный"
    if "воздуш" in low:
        return "Воздушный"
    if "топлив" in low:
        return "Топливный"
    if "салон" in low:
        return "Салонный"
    if "гидравл" in low:
        return "Гидравлический"
    if "трансмисс" in low:
        return "Трансмиссионный"
    return ""


# ----------------------------------------------------------------------------
# Композитный извлекатель: набор атрибутов по группе категории
# ----------------------------------------------------------------------------
_PREORDER_RE = re.compile(r"Предзаказ:\s*\+?(\d+)\s*дн")


def carcity_availability(text: str | None, default: str = "В наличии") -> str:
    """Реальное наличие car-city из 'Предзаказ: +N дней' (лучшее N среди продавцов).

    +0 дней -> 'В наличии'; +N>0 -> 'Под заказ: N дн'. JSON-LD здесь бесполезен
    (всегда InStock), поэтому статус берём из этого поля страницы.
    """
    if not text:
        return default
    days = [int(m) for m in _PREORDER_RE.findall(text)]
    if not days:
        return default
    n = min(days)
    return "В наличии" if n == 0 else f"Под заказ: {n} дн"


def _first_number(s: str | None) -> float | None:
    if not s:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", s)
    return float(m.group().replace(",", ".")) if m else None


_BAD_VALUES = {"", "отсутствует", "нет данных", "-", "—", "не указано"}


def attributes_from_carcity_chars(group: str, chars: dict) -> dict:
    """Маппинг характеристик car-city (`{имя -> [значения]}`) -> наши колонки.

    Принимает много-значный словарь (из nuxt.characteristics): одно-значные поля
    берут первое значение, много-значные (совместимость с авто) — список через «; ».
    Возвращает только непустые значения; недостающее дополнит extract_for_group.
    """
    def first(*keys: str) -> str:
        for k in keys:
            vals = chars.get(k)
            if vals:
                v = str(vals[0]).strip()
                if v.lower() not in _BAD_VALUES:
                    return v
        return ""

    def joined(*keys: str) -> str:
        for k in keys:
            vals = chars.get(k)
            if vals:
                clean = [str(x).strip() for x in vals
                         if str(x).strip().lower() not in _BAD_VALUES]
                if clean:
                    return "; ".join(dict.fromkeys(clean))  # уникальные, порядок сохранён
        return ""

    out: dict[str, object] = {}

    # --- кросс-категорийные (во всех 4 категориях) ---
    if (v := first("Назначение")):
        out["purpose"] = v
    if (v := first("Особенности")):
        out["features"] = v
    if (v := first("Вес", "Вес (гр)", "Вес, кг", "Вес, г", "Масса")):
        out["weight"] = v
    if (v := joined("Марка автомобиля", "Марка авто", "Совместимая марка")):
        out["compatible_brand"] = v
    if (v := joined("Модель автомобиля", "Совместимая модель")):
        out["compatible_model"] = v
    if (v := joined("Год выпуска автомобиля", "Год выпуска")):
        out["compatible_years"] = v

    if group == "tires":
        w = _first_number(first("Ширина профиля"))
        p = _first_number(first("Высота профиля"))
        d = _first_number(first("Диаметр диска", "Посадочный диаметр", "Диаметр"))
        if w:
            out["tire_width"] = int(w)
        if p:
            out["tire_profile"] = int(p)
        if d is not None:
            out["tire_diameter"] = int(d) if float(d).is_integer() else d
        if (li := re.match(r"\s*(\d+)", first("Индекс нагрузки"))):
            out["load_index"] = li.group(1)
        if (si := re.search(r"[A-Za-z]{1,2}", first("Индекс скорости"))):
            out["speed_index"] = si.group(0).upper()
        if (season := detect_season(first("Сезонность", "Сезон"))):
            out["season"] = season
        if (studs := first("Шипы").lower()):
            out["studded"] = ("шип" in studs and "без" not in studs)
        if (rf := first("Run Flat", "RunFlat", "Технология RunFlat").lower()):
            out["runflat"] = rf in ("да", "есть", "yes", "true") or "run" in rf
        if (v := first("Название модели")):
            out["model_name"] = v
        if (v := first("Тип шины")):
            out["tire_type"] = v
        if (v := first("Тип рисунка протектора", "Направленный рисунок протектора",
                       "Рисунок протектора")):
            out["tread_pattern"] = v
        if (v := first("Маркировка внедорожных шин")):
            out["offroad_marking"] = v
        if (v := first("Комплектация")):
            out["set_configuration"] = v
    elif group == "oils":
        if (ot := detect_oil_type(first("Вид масла", "Тип масла", "Основа масла"))):
            out["oil_type"] = ot
        if (vis := parse_viscosity(first("Класс вязкости SAE", "Вязкость по SAE",
                                         "Вязкость", "Вязкость SAE"))):
            out["viscosity"] = vis
        if (vol := _first_number(first("Объем", "Объём", "Объем, л"))):
            out["volume_liters"] = vol
        for key, names in (
            ("engine_type", ("Тип двигателя",)),
            ("specification", ("Допуски", "Класс API", "Класс ACEA", "Спецификация")),
            ("product_line", ("Линейка", "Серия", "Семейство")),
            ("package_type", ("Тип упаковки", "Тип тары", "Вид тары", "Упаковка")),
            ("atf_standard", ("Стандарт ATF",)),
            ("transmission_type", ("Тип коробки передач",)),
            ("hypoid", ("Гипоидное масло",)),
        ):
            if (v := first(*names)):
                out[key] = v
    elif group == "batteries":
        if (c := _first_number(first("Емкость", "Ёмкость", "Емкость АКБ"))):
            out["capacity_ah"] = int(c)
        if (u := _first_number(first("Напряжение"))):
            out["voltage_v"] = int(u)
        if (sc := _first_number(first("Пусковой ток"))):
            out["start_current_a"] = int(sc)
        pol = first("Полярность").lower()
        if "обратн" in pol:
            out["polarity"] = "Обратная"
        elif "прям" in pol:
            out["polarity"] = "Прямая"
        if (bt := first("Тип", "Тип аккумулятора", "Технология")):
            out["battery_type"] = bt
        dims = [x for x in (first("Длина"), first("Ширина"), first("Высота")) if x]
        if dims:
            out["dimensions"] = " × ".join(dims)
        if (tt := first("Тип клемм", "Клеммы", "Расположение клемм")):
            out["terminal_type"] = tt
        if (v := first("Тип корпуса")):
            out["case_type"] = v
    elif group == "filters":
        if (ft := detect_filter_type(first("Тип фильтра", "Тип"))):
            out["filter_type"] = ft
        if (v := first("Артикул производителя", "Артикул")):
            out["manufacturer_article"] = v
    return out


def carcity_oem_numbers(chars: dict) -> list[str]:
    """OEM-номера из характеристик (для Product.oem_numbers)."""
    out: list[str] = []
    for k in ("Запчасть совместима с ОЕМ", "Номер OEM", "OEM", "OEM номер",
              "Оригинальный номер"):
        for v in chars.get(k, []) or []:
            v = str(v).strip()
            if v and v.lower() not in _BAD_VALUES:
                out.append(v)
    return list(dict.fromkeys(out))


def extract_for_group(group: str, name: str, category_text: str = "") -> dict:
    """Собрать атрибуты группы из названия и текста категории.

    Возвращает только ключи, относящиеся к группе (см. models.ATTRS_BY_GROUP);
    отсутствующие значения — пустые/None. Источник — название товара
    (типоразмер шины, вязкость/объём масла) и категория (сезон, тип фильтра).
    """
    name = name or ""
    blob = f"{name} {category_text}".strip()
    if group == "tires":
        d = parse_tire_size(name)
        # Сначала по названию (Ice Guard / Snow Cross / «с шипами» надёжнее),
        # затем по категории — на car-city в siny-letnie встречаются и зимние.
        d["season"] = detect_season(name) or detect_season(category_text)
        d["runflat"] = detect_runflat(name)
        studded = parse_studded(name)
        # Шипы бывают только у зимних: летняя/всесезонная -> заведомо False.
        if studded is None and d["season"] in ("Летняя", "Всесезонная"):
            studded = False
        d["studded"] = studded
        return d
    if group == "oils":
        return {
            "viscosity": parse_viscosity(blob),
            "volume_liters": parse_volume_liters(blob),
            "oil_type": detect_oil_type(blob),
            "engine_type": "",
            "specification": "",
            "product_line": "",
            "package_type": "",
        }
    if group == "batteries":
        return {
            "capacity_ah": parse_capacity_ah(blob),
            "voltage_v": parse_voltage_v(blob),
            "start_current_a": None,
            "polarity": detect_battery_polarity(blob),
            "battery_type": "",
            "dimensions": "",
            "terminal_type": "",
        }
    if group == "filters":
        return {
            "filter_type": detect_filter_type(category_text) or detect_filter_type(name),
            "compatible_brand": "",
            "compatible_model": "",
        }
    return {}
