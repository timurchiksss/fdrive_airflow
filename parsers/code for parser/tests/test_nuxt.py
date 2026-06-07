"""Тесты разбора __NUXT_DATA__ (мультипродавец + характеристики)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freedom_parser.common import nuxt


def test_characteristics_single_and_multi():
    html = (
        'x "Емкость",1460,[4188],"75.0 Ач" '
        'y "Год выпуска автомобиля",1193,[4214,4215],"1997","1998" '
        'z "Полярность",1461,[4208],"прямая" end'
    )
    chars = nuxt.characteristics(html)
    assert chars["Емкость"] == ["75.0 Ач"]
    assert chars["Год выпуска автомобиля"] == ["1997", "1998"]  # хвост не теряем
    assert chars["Полярность"] == ["прямая"]


def test_find_offers_multiseller():
    # devalue-массив: значения хранятся в массиве, поля-объекты ссылаются по индексу
    arr = [
        "root",            # 0
        "MPS",             # 1
        75106,             # 2
        0,                 # 3
        30,                # 4
        {"name": 1},       # 5  company1
        {"per_unit": 2, "per_package": 2},  # 6  price1
        {"company": 5, "price": 6, "quantity_in_stock": 4,
         "delivery_days": 3, "preorder": 3, "id": 99},          # 7 offer1
        "АЛМАЛЭНД",        # 8
        107184,            # 9
        {"name": 8},       # 10 company2
        {"per_unit": 9, "per_package": 9},  # 11 price2
        {"company": 10, "price": 11, "quantity_in_stock": 4,
         "delivery_days": 3, "preorder": 3, "id": 100},         # 12 offer2
    ]
    offers = nuxt.find_offers(arr)
    sellers = {o["seller"]: o["price"] for o in offers}
    assert sellers == {"MPS": 75106, "АЛМАЛЭНД": 107184}
    assert offers[0]["quantity_in_stock"] == 30
    assert offers[0]["delivery_days"] == 0


def test_find_offers_dedup():
    arr = [
        "root", "MPS", 1000,
        {"name": 1},                       # 3 company
        {"per_unit": 2},                   # 4 price
        {"company": 3, "price": 4, "quantity_in_stock": 5, "delivery_days": 5},  # 5 offer
        {"company": 3, "price": 4, "quantity_in_stock": 5, "delivery_days": 5},  # 6 dup
    ]
    assert len(nuxt.find_offers(arr)) == 1


def test_parse_nuxt_data_absent():
    assert nuxt.parse_nuxt_data("<html>no data</html>") == []


def test_physical_fields_from_product_node():
    # Товарный узел ссылается на вес/габариты по индексу (как в реальном payload).
    arr = [
        "root",                # 0
        "Моторное масло X",    # 1 name
        "maslo-x",             # 2 slug
        2750,                  # 3 weight (г)
        100,                   # 4 length (мм)
        50,                    # 5 width
        20,                    # 6 height
        {"name": 1, "slug": 2, "weight": 3, "length": 4, "width": 5,
         "height": 6, "offers": 0, "attributes": 0},  # 7 продукт
    ]
    phys = nuxt.physical_fields(arr, name="Моторное масло X")
    assert phys == {"weight": 2750, "length": 100, "width": 50, "height": 20}


def test_physical_fields_skips_zero_and_label_node():
    arr = [
        "root",                # 0
        "Товар",               # 1
        "slug",                # 2
        0,                     # 3 weight = 0 -> пропустить
        0, 0, 0,               # 4,5,6 габариты = 0
        {"name": 1, "slug": 2, "weight": 3, "length": 4, "width": 5,
         "height": 6, "offers": 0, "attributes": 0},  # 7 продукт (всё 0)
        # узел-ярлыки: те же физ-ключи, но без offers/slug -> игнор
        {"weight": 1, "length": 1, "width": 1, "height": 1},  # 8
    ]
    assert nuxt.physical_fields(arr, name="Товар") == {}


def test_physical_fields_picks_richest_when_no_name():
    arr = [
        "root", "A", "a", 500, 0, 0, 0,
        {"name": 1, "slug": 2, "weight": 3, "length": 4, "width": 5,
         "height": 6, "offers": 0},               # 7 бедный узел
        {"name": 1, "slug": 2, "weight": 3, "length": 4, "width": 5,
         "height": 6, "offers": 0, "attributes": 0, "reviews": 0},  # 8 богатый
    ]
    assert nuxt.physical_fields(arr) == {"weight": 500}
