# Freedom Parser — car-city.kz + pitstopshop.kz

Парсер автотоваров для проекта **Freedom Holding × SDU «Master Data Catalog»**.
Часть **Nuradil Abyz**: два назначенных сайта, сбор в широкие CSV, совместимые с
моделью мастер-каталога (PDF §3.4/§4).

| Сайт | Категории | Собрано |
|------|-----------|---------|
| **car-city.kz** | шины, масла, фильтры, АКБ | 26 055 товаров → **43 798 строк** |
| **pitstopshop.kz** | только шины | 7 250 моделей → **131 086 размеров** |
| **altraauto.kz** | только шины | 23 019 карточек (2 608 «в наличии» + 20 411 «под заказ») |
| **expertoil.kz** | масла + АКБ | 143 карточки (127 масел + 16 АКБ), все «в наличии» |

> Граница задачи — **парсинг + извлечение атрибутов**. Нормализация и сведение
> источников в единый `sku_id` — отдельный командный этап (не входит сюда).

---

## 📂 Где результат и что в каждом файле

Каждый сайт — в своей папке `data/<site>/`. Полное описание — в [`data/README.md`](data/README.md).

### `data/carcity/`
| Файл | Что это |
|------|---------|
| **carcity_products.csv** | Полный «сырой» снимок: **1 строка = товар × предложение продавца**, все 4 категории вместе. У товара бывает несколько продавцов → несколько строк. |
| **carcity_tires.csv** | Разрез: только **шины** (8 890). |
| **carcity_oils.csv** | Разрез: только **масла** (2 073). |
| **carcity_batteries.csv** | Разрез: только **АКБ** (199). |
| **carcity_filters.csv** | Разрез: только **фильтры** (32 636). |
| **carcity_price_history.csv** | История цен: 1 строка на предложение с `price` и датой `parsed_at`. |
| **carcity_quality_gaps.csv** | Контроль качества: строки с пустыми обязательными атрибутами. |
| `carcity_uncategorized.csv` | Нераспознанные категории (сейчас **0** — значит ничего не потеряно). |
| `state.sqlite` | Служебный файл (инкрементальные прогоны). Не для проверки. |

> `products.csv` и 4 разреза по категориям — **одни и те же данные**; разрезы удобны
> для проверки по категориям, `products.csv` — полный сырой слой.

### `data/altraauto/`
| Файл | Что это |
|------|---------|
| **altraauto_products.csv** | Снимок: 23 019 шин, 1 строка = товар. «В наличии» (2 608) — с ценой; «Под заказ» (20 411) — `price` пустой, `availability="Под заказ"`. |
| **altraauto_tires.csv** | Разрез: те же шины с шинными колонками (полный дубль `products`, т.к. сайт только шины). |
| **altraauto_price_history.csv** | История цен только по тем, у кого цена > 0 (2 578 строк). |
| **altraauto_quality_gaps.csv** | Контроль качества: строки с пустыми обязательными атрибутами. |
| `state.sqlite` | Служебный файл. Не для проверки. |

### `data/pitstopshop/`
| Файл | Что это |
|------|---------|
| **pitstopshop_products.csv** | Таблица шин (она же снимок): **1 строка = размер шины**, и «в наличии», и «под заказ». Атрибуты модели продублированы в каждый размер. |
| **pitstopshop_price_history.csv** | История цен (только размеры «в наличии» — 12 509). |
| **pitstopshop_quality_gaps.csv** | Контроль качества: строки с пустыми атрибутами. |
| `state.sqlite` | Служебный файл. Не для проверки. |

### `data/expertoil/`
| Файл | Что это |
|------|---------|
| **expertoil_products.csv** | Снимок: масла + АКБ из expertoil.kz, **1 строка = товар × предложение** (продавец один — сам магазин). Цена — у тех, где есть кнопка «В корзину»; иначе `availability="Под заказ"`. |
| **expertoil_price_history.csv** | История цен (по строке на товар при `price>0`). |
| **expertoil_quality_gaps.csv** | Контроль качества: строки с пустыми обязательными атрибутами. |
| `state.sqlite` | Служебный файл. Не для проверки. |

---

## 📖 Как читать CSV

Открывать **строками** — иначе теряются ведущие нули в `id` и портятся типы
(`5W-30`, артикулы, индексы — это текст, не числа):

```python
import pandas as pd
df = pd.read_csv("data/carcity/carcity_tires.csv", dtype=str, keep_default_na=False)
```

Кодировка `utf-8-sig` (Excel открывает напрямую, кириллица не «кракозябрится»).

## 🧩 Колонки

**Паспорт товара:** `source, source_product_id, source_url, category_group,
category_l1, category_leaf, name, brand, article_sku, oem_numbers, image_url, parsed_at`

**Предложение продавца:** `seller_name, price, old_price, currency, availability,
quantity_in_stock, delivery_days, city`

**Атрибуты по категориям** (заполняются в своей таблице):
- **Шины:** `tire_width, tire_profile, tire_diameter, season, load_index, speed_index,
  runflat, studded, model_name, tire_type, tread_pattern, offroad_marking,
  set_configuration, brand_country, reinforced`
- **Масла:** `viscosity, volume_liters, oil_type, engine_type, specification,
  product_line, package_type, atf_standard, transmission_type, hypoid`
- **АКБ:** `capacity_ah, voltage_v, start_current_a, polarity, battery_type, dimensions,
  terminal_type, case_type`
- **Фильтры:** `filter_type, manufacturer_article`
- **Общие доп-поля:** `purpose, features, weight, compatible_brand, compatible_model,
  compatible_years`

## ✅ Принципы (чтобы не было вопросов при проверке)

- **Все предложения продавцов.** car-city: у ~36% товаров 2–4 продавца — каждый
  отдельной строкой (разные `price`/`seller_name`), ничего не схлопываем.
- **Все размеры шин.** pitstop: каждый размер — отдельная строка, и «в наличии», и
  «под заказ» (у вторых `price` пустой, `availability = Под заказ`).
- **Повторяемость + инкремент.** Повторный прогон ловит новые/изменившиеся товары и
  дописывает только их в `price_history`.

## ⚙️ Как работает altraauto

Кастомная серверная платформа, шины. **Обнаружение** — через `sitemap-index.xml`,
подкарта `products-shiny.xml` (в наличии, обычный XML) + `out_of_stock-*.xml.gz`
(под заказ, **gzip-сжатый XML**). Дедуп по числовому `id` из URL; при коллизии
выигрывает запись «в наличии». **Атрибуты** — серверный HTML, блок
`div._parameter > ul > li > span+span` (без JSON-LD и без `__NUXT_DATA__`).
Один продавец — сам магазин (`seller_name = "altraauto"`); цена — текстом
«50 900 тг»; шипованность — из URL (`-spike-` / `-no-spike-`); `source_product_id`
— числовой id из URL (`...-id-NNNN[-...]-s.html`).

## ⚙️ Как работает expertoil

Простой PHP/nginx сайт (масла + АКБ). **Обнаружение** — пагинацией листингов
`/ru/catalog/masla_490/?p=N` и `/ru/catalog/akkumulyatory_490/?p=N` до первой
пустой страницы; ссылки на товары — `div.product-item h3 a[href]`. **JSON-LD /
microdata / OG отсутствуют полностью** — только серверный HTML. Имя — `h1` в
`div.el_desc`; цена — `div.el_desc span.price` (regex `Цена:\s*([\d\s]+)\s*тг`);
наличие — по кнопке `a.button` с `onclick="add_to_basket1(NNN)"` («В наличии»),
иначе «Под заказ»; картинка — `div.el_img img@src` (`/upload/images/big/...`).
**Бренд** — из URL-сегмента: `shell_521` → `Shell`, `akb-exide_383` → `Exide`,
`united-oil_...` → `United Oil`. У большинства карточек **структурного блока
характеристик НЕТ**, у части — вставлен HTML из Yandex.Market со строками
`span[data-auto="product-spec"]` (лейбл) и `div.b2ZT4` (значение). Поэтому
атрибуты (вязкость, объём масла, ёмкость АКБ) в основном добываются ИЗ НАЗВАНИЯ
(`extract_for_group`). Один продавец — сам магазин (`seller_name="expertoil"`),
город — Алматы. `source_product_id` — путь после `/ru/catalog/`.

## ⚠️ Известные особенности (это норма, не баги)

- **`weight`** — заявленный вес из карточки (часто брутто/упаковка, бывает завышен);
  для raw берём как есть, нормализация единиц — на следующем этапе.
- **Масла `viscosity` ~68%** по всей группе «масла» — потому что трансмиссионные/спец-масла
  не имеют SAE-вязкости. По **моторным** маслам отдельно — 97%.
- **pitstop:** `article_sku` пустой (артикул только на странице размера — не тянем,
  id берём из URL); `image_url` — общая картинка модели; `brand_country`/`reinforced`
  есть только у pitstop (у car-city пусто — это норма).
- **`city`** у car-city пуст — маркетплейс не отдаёт город (цена общереспубликанская).
- **altraauto:** один продавец (мультипродавца нет); `oem_numbers`, авто-совместимость
  (`compatible_brand`/`compatible_model`/`compatible_years`), `brand_country` и `weight`
  пусты — сайт не отдаёт эти поля для шин.
- **expertoil:** карточки **не имеют структурного блока характеристик** — поэтому
  атрибуты добываются из имени (вязкость 81%, объём 96%, ёмкость АКБ 100%). `oil_type`
  ~10% — в имени редко указано «синтетическое/полусинтетическое»; для АКБ `voltage_v`
  везде 12 (стандарт авто, сайт не дублирует); один продавец, город Алматы;
  `article_sku`, `oem_numbers`, `start_current_a` пусты.

KPI атрибуции ≥80% выполнен по обязательным полям обоих сайтов (см. `quality_gaps`).

---

## 🔧 Запустить заново

```bash
pip install -r requirements.txt                          # requests, beautifulsoup4, lxml

python run.py --site carcity --categories all            # car-city, 4 категории
python split_by_category.py                              # → 4 таблицы по категориям
python profile.py --site carcity                         # KPI + quality_gaps

python run.py --site pitstopshop --roots tyre,gruz,sh,moto,atv   # pitstop, все разделы
python profile.py --site pitstopshop
```

Каждый сайт пишет в `data/<site>/` со своим `state.sqlite` — сайты можно гнать
параллельно. Тесты: `python -m pytest -q` (76 тестов: парсеры атрибутов, разбор
`__NUXT_DATA__`, разбор pitstop, robots.txt).

Парсинг вежливый: честный `User-Agent`, проверка `robots.txt`, пауза между запросами,
ретраи. JS не требуется — оба сайта отдают серверный HTML.
