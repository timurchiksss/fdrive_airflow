-- ============================================================================
--  §4.5  master.category_attributes — допустимые атрибуты по категориям.
--  Часть Madi. Декларативно по семействам: семейство категории = её предок
--  2-го уровня в дереве (2=oils, 30=tires, 50=batteries, 60=filters).
--  Атрибут -> семейство: то семейство, в чьём источнике cleanned.* есть колонка
--  с таким именем. brand и image_url — универсальны (во всех семействах).
--  Без temp-таблиц (только CTE) — безопасно для Airflow/autocommit.
--  Идемпотентно: DROP ... CASCADE + пересоздание.
-- ============================================================================
SET search_path = master, public;

DROP TABLE IF EXISTS master.category_attributes CASCADE;
CREATE TABLE master.category_attributes (
    category_id        bigint      NOT NULL,
    category           text,
    attribute_group_id smallint,
    attribute_group    text,
    attribute_id       varchar(20) NOT NULL,
    attribute          text,
    PRIMARY KEY (category_id, attribute_id));

INSERT INTO master.category_attributes
       (category_id, category, attribute_group_id, attribute_group, attribute_id, attribute)
WITH RECURSIVE
attr_dom(attr_name, domain) AS (VALUES
    -- oils
    ('brand','oils'),('product_line','oils'),('viscosity','oils'),('volume_liters','oils'),
    ('oil_type','oils'),('engine_type','oils'),('specification','oils'),('package_type','oils'),
    ('acea_class','oils'),('approvals','oils'),('image_url','oils'),
    -- tires
    ('brand','tires'),('tire_width','tires'),('tire_profile','tires'),('tire_diameter','tires'),
    ('season','tires'),('load_index','tires'),('speed_index','tires'),('runflat','tires'),
    ('studded','tires'),('weight','tires'),('image_url','tires'),
    -- batteries
    ('brand','batteries'),('capacity_ah','batteries'),('voltage_v','batteries'),('start_current_a','batteries'),
    ('polarity','batteries'),('battery_type','batteries'),('dimensions','batteries'),('terminal_type','batteries'),
    ('weight','batteries'),('features','batteries'),('length','batteries'),('width','batteries'),
    ('height','batteries'),('image_url','batteries'),
    -- filters
    ('brand','filters'),('filter_type','filters'),('compatible_brand','filters'),
    ('compatible_model','filters'),('oem_number','filters'),('additional_information','filters'),
    ('image_url','filters')),
up AS (
    SELECT category_id, category_id AS anc, level, parent_category_id FROM master.categories
    UNION ALL
    SELECT u.category_id, c.category_id, c.level, c.parent_category_id
    FROM up u JOIN master.categories c ON c.category_id = u.parent_category_id),
cat_dom AS (
    SELECT category_id,
           CASE anc WHEN 2 THEN 'oils' WHEN 30 THEN 'tires'
                    WHEN 50 THEN 'batteries' WHEN 60 THEN 'filters' END AS domain
    FROM up WHERE level = 2)
SELECT DISTINCT c.category_id, c.name,
       aag.attribute_group_id, aag.attribute_group, a.id, a.name
FROM cat_dom d
JOIN master.categories c ON c.category_id = d.category_id
JOIN attr_dom ad         ON ad.domain = d.domain
JOIN master.attributes a ON a.name = ad.attr_name
LEFT JOIN master.attributes_attribute_groups aag ON aag.attribute_id = a.id
WHERE d.domain IS NOT NULL;

ANALYZE master.category_attributes;
