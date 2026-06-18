"""Seeds the static category tree used by matching_pipeline.py's get_category_id().

Safe to re-run any time: it fully replaces matching.categories with this canonical
definition (if_exists="replace"), so running it twice is a no-op in effect. """

import logging
import os

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# (category_id, name, level, parent_category_id, parent_category, is_leaf)
CATEGORY_ROWS = [
    # ROOT
    (1, 'Автотовары', 1, None, None, False),

    # OILS & FLUIDS
    (2, 'Масла и жидкости', 2, 1, 'Автотовары', False),

    (3, 'Моторные масла', 3, 2, 'Масла и жидкости', False),
    (4, 'Синтетические моторные масла', 4, 3, 'Моторные масла', True),
    (5, 'Полусинтетические моторные масла', 4, 3, 'Моторные масла', True),
    (6, 'Минеральные моторные масла', 4, 3, 'Моторные масла', True),
    (7, 'Промывочные масла', 4, 3, 'Моторные масла', True),

    (8, 'Трансмиссионные масла', 3, 2, 'Масла и жидкости', False),
    (9, 'ATF масла', 4, 8, 'Трансмиссионные масла', True),
    (10, 'CVT масла', 4, 8, 'Трансмиссионные масла', True),
    (11, 'Масла для МКПП', 4, 8, 'Трансмиссионные масла', True),
    (12, 'Масла для дифференциала', 4, 8, 'Трансмиссионные масла', True),

    (13, 'Гидравлические масла', 3, 2, 'Масла и жидкости', True),
    (14, 'Жидкости ГУР', 3, 2, 'Масла и жидкости', True),

    (15, 'Тормозные жидкости', 3, 2, 'Масла и жидкости', False),
    (16, 'DOT 3', 4, 15, 'Тормозные жидкости', True),
    (17, 'DOT 4', 4, 15, 'Тормозные жидкости', True),
    (18, 'DOT 5', 4, 15, 'Тормозные жидкости', True),

    (19, 'Антифризы и охлаждающие жидкости', 3, 2, 'Масла и жидкости', False),
    (20, 'Концентрат антифриза', 4, 19, 'Антифризы и охлаждающие жидкости', True),
    (21, 'Готовый антифриз', 4, 19, 'Антифризы и охлаждающие жидкости', True),

    (22, 'Присадки и очистители', 3, 2, 'Масла и жидкости', False),
    (23, 'Топливные присадки', 4, 22, 'Присадки и очистители', True),
    (24, 'Присадки в масло', 4, 22, 'Присадки и очистители', True),
    (25, 'Очистители форсунок', 4, 22, 'Присадки и очистители', True),
    (26, 'Очистители двигателя', 4, 22, 'Присадки и очистители', True),

    # TYRES
    (30, 'Шины', 2, 1, 'Автотовары', False),

    (31, 'Легковые шины', 3, 30, 'Шины', False),
    (32, 'Летние легковые шины', 4, 31, 'Легковые шины', True),
    (33, 'Зимние легковые шины', 4, 31, 'Легковые шины', False),
    (34, 'Зимние шипованные легковые шины', 5, 33, 'Зимние легковые шины', True),
    (35, 'Зимние нешипованные легковые шины', 5, 33, 'Зимние легковые шины', True),
    (36, 'Всесезонные легковые шины', 4, 31, 'Легковые шины', True),

    (37, 'Шины для внедорожников и кроссоверов', 3, 30, 'Шины', False),
    (38, 'Летние шины SUV', 4, 37, 'Шины для внедорожников и кроссоверов', True),
    (39, 'Зимние шины SUV', 4, 37, 'Шины для внедорожников и кроссоверов', True),
    (40, 'Всесезонные шины SUV', 4, 37, 'Шины для внедорожников и кроссоверов', True),

    (41, 'Грузовые шины', 3, 30, 'Шины', False),
    (42, 'Шины для лёгких грузовиков', 4, 41, 'Грузовые шины', True),
    (43, 'Шины для тяжёлых грузовиков', 4, 41, 'Грузовые шины', True),

    (44, 'Мотошины', 3, 30, 'Шины', True),
    (45, 'Сельскохозяйственные шины', 3, 30, 'Шины', True),
    (46, 'Шины для спецтехники', 3, 30, 'Шины', True),

    # BATTERIES
    (50, 'Аккумуляторы', 2, 1, 'Автотовары', False),

    (51, 'Аккумуляторы для легковых авто', 3, 50, 'Аккумуляторы', False),
    (52, 'Стандартные аккумуляторы', 4, 51, 'Аккумуляторы для легковых авто', True),
    (53, 'AGM аккумуляторы', 4, 51, 'Аккумуляторы для легковых авто', True),
    (54, 'EFB аккумуляторы', 4, 51, 'Аккумуляторы для легковых авто', True),
    (55, 'GEL аккумуляторы', 4, 51, 'Аккумуляторы для легковых авто', True),

    (56, 'Аккумуляторы для грузовиков', 3, 50, 'Аккумуляторы', True),
    (57, 'Аккумуляторы для мотоциклов', 3, 50, 'Аккумуляторы', True),

    # FILTERS
    (60, 'Фильтры', 2, 1, 'Автотовары', False),
    (61, 'Воздушный фильтр', 3, 60, 'Фильтры', True),
    (62, 'Масляный фильтр', 3, 60, 'Фильтры', True),
    (63, 'Салонный фильтр', 3, 60, 'Фильтры', True),
    (64, 'Топливный фильтр', 3, 60, 'Фильтры', True),
    (65, 'Трансмиссионный фильтр', 3, 60, 'Фильтры', True),
    (66, 'Гидравлический фильтр', 3, 60, 'Фильтры', True),

    # UNCLASSIFIED
    (999, 'Неклассифицировано', 2, 1, 'Автотовары', True),
]

CATEGORY_COLUMNS = ['category_id', 'name', 'level', 'parent_category_id', 'parent_category', 'is_leaf']


def get_engine() -> Engine:
    host = os.environ.get("DB_HOST") or os.environ.get("PGHOST", "localhost")
    port = os.environ.get("DB_PORT") or os.environ.get("PGPORT", "5432")
    name = os.environ.get("DB_NAME") or os.environ.get("PGDATABASE", "fdrive")
    user = os.environ.get("DB_USER") or os.environ.get("PGUSER", "postgres")
    password = os.environ.get("DB_PASSWORD") or os.environ.get("PGPASSWORD", "")
    return create_engine(f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}")


def q_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def build_categories_df() -> pd.DataFrame:
    categories = pd.DataFrame(CATEGORY_ROWS, columns=CATEGORY_COLUMNS)
    categories["status"] = "active"
    return categories


def ensure_categories(engine: Engine) -> None:
    output_schema = os.environ.get("MATCH_SCHEMA", "matching")
    categories = build_categories_df()

    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {q_ident(output_schema)}"))

    categories.to_sql("categories", engine, schema=output_schema, if_exists="replace", index=False)
    logger.info("Saved %s categories (%s leaf) to %s.categories",
                len(categories), categories["is_leaf"].sum(), output_schema)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = get_engine()
    ensure_categories(engine)


if __name__ == "__main__":
    main()
