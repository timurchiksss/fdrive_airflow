CREATE TABLE master.attributes (
	id VARCHAR(20) PRIMARY KEY,
	name VARCHAR(100),
	unit VARCHAR(100), 
	status VARCHAR(20)
);

INSERT INTO master.attributes (id, name, unit, status) 
WITH cols AS (
    SELECT DISTINCT
        column_name AS name,
        data_type AS unit
    FROM information_schema.columns
    WHERE table_schema = 'cleanned'
)
SELECT
    'main_' || LPAD(ROW_NUMBER() OVER (ORDER BY name)::text, 3, '0') AS id,
    name,
    unit,
    'active' AS status
FROM cols
ORDER BY name;

DELETE FROM master.attributes
WHERE name IN (
    'load_id',
    'loaded_at',
    'parsed_at',
    'cleaned_at',
    'source',
    'source_file',
    'source_product_id',
    'source_url',
    'article_sku',
    'product_name',
    'normalized_name', 
    
);

DELETE FROM master.attributes 
WHERE name IN (
	'category_group', 
	'price', 
	'old_price', 
	'currency', 
	'availability', 
	'city', 
	'image_url', 
	'rating', 
	'reviews_count', 
	'seller_count'
);


WITH ordered AS (
    SELECT
        ctid,
        ROW_NUMBER() OVER (ORDER BY name) AS rn
    FROM master.attributes
)
UPDATE master.attributes a 
SET id = 'main_' || LPAD(ordered.rn::text, 3, '0')
FROM ordered
WHERE a.ctid = ordered.ctid;




CREATE TABLE master.attribute_groups (
	id INTEGER primary key, 
	name VARCHAR(100), 
	status VARCHAR(20)
);

INSERT INTO master.attribute_groups (id, name, status)
VALUES 
	(1, 'Основные', 'active'), 
	(2, 'Технические характеристики', 'active'),
	(3, 'Размеры', 'active'), 
	(4, 'Совместимость', 'active'), 
	(5, 'Дополнительно', 'active');




CREATE TABLE master.attributes_attribute_groups (
    attribute_group_id  INTEGER,
    attribute_group     VARCHAR(100),
    attribute_id        VARCHAR(20),
    attribute           VARCHAR(100)
);


INSERT INTO master.attributes_attribute_groups
    (attribute_group_id, attribute_group, attribute_id, attribute)
VALUES
  (1, 'Основные', 'main_001',  'brand'),
  (1, 'Основные', 'main_002',  'product_line'),
  (1, 'Основные', 'main_003',  'oil_type'),
  (1, 'Основные', 'main_004',  'engine_type'),
  (1, 'Основные', 'main_005',  'battery_type'),
  (1, 'Основные', 'main_006',  'filter_type'),
  (1, 'Основные', 'main_007',  'season'),
  (1, 'Основные', 'main_008',  'studded'),
  (1, 'Основные', 'main_009',  'runflat'),
  (1, 'Основные', 'main_010', 'package_type'),
  (1, 'Основные', 'main_011', 'polarity'),
  (1, 'Основные', 'main_012', 'terminal_type'),
  (2, 'Технические характеристики', 'main_013', 'viscosity'),
  (2, 'Технические характеристики', 'main_014', 'volume_liters'),
  (2, 'Технические характеристики', 'main_015', 'capacity_ah'),
  (2, 'Технические характеристики', 'main_016', 'voltage_v'),
  (2, 'Технические характеристики', 'main_017', 'start_current_a'),
  (2, 'Технические характеристики', 'main_018', 'load_index'),
  (2, 'Технические характеристики', 'main_019', 'speed_index'),
  (2, 'Технические характеристики', 'main_020', 'tire_width'),
  (2, 'Технические характеристики', 'main_021', 'tire_profile'),
  (2, 'Технические характеристики', 'main_022', 'tire_diameter'),
  (2, 'Технические характеристики', 'main_023', 'acea_class'),
  (2, 'Технические характеристики', 'main_024', 'specification'),
  (2, 'Технические характеристики', 'main_025', 'approvals'),
  (3, 'Размеры', 'main_026', 'width'),
  (3, 'Размеры', 'main_027', 'height'),
  (3, 'Размеры', 'main_028', 'length'),
  (3, 'Размеры', 'main_029', 'dimensions'),
  (3, 'Размеры', 'main_030', 'weight'),
  (4, 'Совместимость', 'main_031', 'compatible_brand'),
  (4, 'Совместимость', 'main_032', 'compatible_model'),
  (4, 'Совместимость', 'main_033', 'oem_number'),
  (5, 'Дополнительно', 'main_034', 'features'),
  (5, 'Дополнительно', 'main_035', 'additional_information');



ALTER TABLE master.attributes_attribute_groups
ADD CONSTRAINT fk_aag_group
FOREIGN KEY (attribute_group_id)
REFERENCES master.attribute_groups(id);

ALTER TABLE master.attributes_attribute_groups
ADD CONSTRAINT fk_aag_attribute
FOREIGN KEY (attribute_id)
REFERENCES master.attributes(id);



SELECT conname, contype 
FROM pg_constraint 
WHERE conrelid = 'master.attributes_attribute_groups'::regclass;



INSERT INTO master.attributes (id, name, unit, status)
VALUES ('main_036', 'image_url', 'text', 'active');

INSERT INTO master.attributes_attribute_groups (attribute_group_id, attribute_group, attribute_id, attribute)
VALUES (5, 'Дополнительно', 'main_036', 'image_url');

