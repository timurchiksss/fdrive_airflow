ALTER TABLE master.skus
    ADD CONSTRAINT skus_pkey PRIMARY KEY (id);

ALTER TABLE master.skus
    ADD CONSTRAINT skus_category_id_fkey
    FOREIGN KEY (category_id) REFERENCES master.categories (category_id);

ALTER TABLE master.sku_source_mapping
    ADD CONSTRAINT sku_source_mapping_sku_id_fkey
    FOREIGN KEY (sku_id) REFERENCES master.skus (id);

CREATE TABLE master.sku_attribute_values (
    sku_id       text NOT NULL,
    attribute_id smallint NOT NULL,
    attribute    text,
    value        text,
    CONSTRAINT sku_attribute_values_sku_id_fkey
        FOREIGN KEY (sku_id) REFERENCES master.skus (id),
    CONSTRAINT sku_attribute_values_attribute_id_fkey
        FOREIGN KEY (attribute_id) REFERENCES master.attributes (id)
);

CREATE INDEX idx_sav_sku_id ON master.sku_attribute_values (sku_id);
CREATE INDEX idx_sav_attribute_id ON master.sku_attribute_values (attribute_id);

CREATE TABLE master.tmp_oils_union AS
SELECT source, source_product_id, brand, viscosity, volume_liters, oil_type, engine_type,
       specification, product_line, package_type, acea_class, approvals, image_url, normalized_name
FROM cleanned.carcity_oils
UNION ALL
SELECT source, source_product_id, brand, viscosity, volume_liters, oil_type, engine_type,
       specification, product_line, package_type, acea_class, approvals, image_url, normalized_name
FROM cleanned.fdrive_oils
UNION ALL
SELECT source, source_product_id, brand, viscosity, volume_liters, oil_type, engine_type,
       specification, product_line, package_type, acea_class, approvals, image_url, normalized_name
FROM cleanned.forte_market_oils
UNION ALL
SELECT source, source_product_id, brand, viscosity, volume_liters, oil_type, engine_type,
       specification, product_line, package_type, acea_class, approvals, image_url, normalized_name
FROM cleanned.satu_oils;

--oils
CREATE TABLE master.tmp_oils_sku_map AS
SELECT s.id AS sku_id, elem->>'id' AS source_product_id, elem->>'source' AS source
FROM master.skus s
CROSS JOIN LATERAL jsonb_array_elements(
    CASE
        WHEN jsonb_typeof(s.source_id) = 'array'  THEN s.source_id
        WHEN jsonb_typeof(s.source_id) = 'string' THEN (s.source_id #>> '{}')::jsonb
        ELSE '[]'::jsonb
    END
) AS elem;

CREATE TABLE master.tmp_oils_with_sku AS
SELECT u.*, m.sku_id
FROM master.tmp_oils_union u
JOIN master.tmp_oils_sku_map m
  ON m.source = u.source AND m.source_product_id = u.source_product_id;

INSERT INTO master.sku_attribute_values (sku_id, attribute_id, attribute, value)
SELECT sku_id, 'main_031', 'viscosity', mode() WITHIN GROUP (ORDER BY viscosity)
FROM master.tmp_oils_with_sku WHERE viscosity IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_033', 'volume_liters', mode() WITHIN GROUP (ORDER BY volume_liters)::text
FROM master.tmp_oils_with_sku WHERE volume_liters IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_017', 'oil_type', mode() WITHIN GROUP (ORDER BY oil_type)
FROM master.tmp_oils_with_sku WHERE oil_type IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_010', 'engine_type', mode() WITHIN GROUP (ORDER BY engine_type)
FROM master.tmp_oils_with_sku WHERE engine_type IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_023', 'specification', mode() WITHIN GROUP (ORDER BY specification)
FROM master.tmp_oils_with_sku WHERE specification IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_020', 'product_line', mode() WITHIN GROUP (ORDER BY product_line)
FROM master.tmp_oils_with_sku WHERE product_line IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_018', 'package_type', mode() WITHIN GROUP (ORDER BY package_type)
FROM master.tmp_oils_with_sku WHERE package_type IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_001', 'acea_class', mode() WITHIN GROUP (ORDER BY acea_class)
FROM master.tmp_oils_with_sku WHERE acea_class IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_003', 'approvals', mode() WITHIN GROUP (ORDER BY approvals)
FROM master.tmp_oils_with_sku WHERE approvals IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_036', 'image_url', mode() WITHIN GROUP (ORDER BY image_url)
FROM master.tmp_oils_with_sku WHERE image_url IS NOT NULL GROUP BY sku_id;

DROP TABLE master.tmp_oils_union;
DROP TABLE master.tmp_oils_sku_map;
DROP TABLE master.tmp_oils_with_sku;

--tires
CREATE TABLE master.tmp_tires_union AS
SELECT source, source_product_id, brand, tire_width, tire_profile, tire_diameter,
       season, load_index, speed_index, studded, runflat, model_name, weight, image_url, normalized_name
FROM cleanned.carcity_tires
UNION ALL
SELECT source, source_product_id, brand, tire_width, tire_profile, tire_diameter,
       season, load_index, speed_index, studded, runflat, model_name, weight, image_url, normalized_name
FROM cleanned.fdrive_tires
UNION ALL
SELECT source, source_product_id, brand, tire_width, tire_profile, tire_diameter,
       season, load_index, speed_index, studded, runflat, model_name, weight, image_url, normalized_name
FROM cleanned.forte_market_tires
UNION ALL
SELECT source, source_product_id, brand, tire_width, tire_profile, tire_diameter,
       season, load_index, speed_index, studded, runflat, model_name, weight, image_url, normalized_name
FROM cleanned.satu_tires;

CREATE TABLE master.tmp_tires_sku_map AS
SELECT s.id AS sku_id, elem->>'id' AS source_product_id, elem->>'source' AS source
FROM master.skus s
CROSS JOIN LATERAL jsonb_array_elements(
    CASE
        WHEN jsonb_typeof(s.source_id) = 'array'  THEN s.source_id
        WHEN jsonb_typeof(s.source_id) = 'string' THEN (s.source_id #>> '{}')::jsonb
        ELSE '[]'::jsonb
    END
) AS elem;

CREATE TABLE master.tmp_tires_with_sku AS
SELECT u.*, m.sku_id
FROM master.tmp_tires_union u
JOIN master.tmp_tires_sku_map m
  ON m.source = u.source AND m.source_product_id = u.source_product_id;

INSERT INTO master.sku_attribute_values (sku_id, attribute_id, attribute, value)
SELECT sku_id, 'main_030', 'tire_width', mode() WITHIN GROUP (ORDER BY tire_width)::text
FROM master.tmp_tires_with_sku WHERE tire_width IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_029', 'tire_profile', mode() WITHIN GROUP (ORDER BY tire_profile)::text
FROM master.tmp_tires_with_sku WHERE tire_profile IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_028', 'tire_diameter', mode() WITHIN GROUP (ORDER BY tire_diameter)::text
FROM master.tmp_tires_with_sku WHERE tire_diameter IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_022', 'season', mode() WITHIN GROUP (ORDER BY season)
FROM master.tmp_tires_with_sku WHERE season IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_015', 'load_index', mode() WITHIN GROUP (ORDER BY load_index)
FROM master.tmp_tires_with_sku WHERE load_index IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_024', 'speed_index', mode() WITHIN GROUP (ORDER BY speed_index)
FROM master.tmp_tires_with_sku WHERE speed_index IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_026', 'studded', mode() WITHIN GROUP (ORDER BY studded)::text
FROM master.tmp_tires_with_sku WHERE studded IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_021', 'runflat', mode() WITHIN GROUP (ORDER BY runflat)::text
FROM master.tmp_tires_with_sku WHERE runflat IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_034', 'weight', mode() WITHIN GROUP (ORDER BY weight)
FROM master.tmp_tires_with_sku WHERE weight IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_036', 'image_url', mode() WITHIN GROUP (ORDER BY image_url)
FROM master.tmp_tires_with_sku WHERE image_url IS NOT NULL GROUP BY sku_id;

DROP TABLE master.tmp_tires_union;
DROP TABLE master.tmp_tires_sku_map;
DROP TABLE master.tmp_tires_with_sku;

--batteries
CREATE TABLE master.tmp_batteries_union AS
SELECT source, source_product_id, brand, capacity_ah, voltage_v, start_current_a,
       polarity, battery_type, dimensions, terminal_type, weight, features,
       length, width, height, image_url, normalized_name
FROM cleanned.carcity_batteries
UNION ALL
SELECT source, source_product_id, brand, capacity_ah, voltage_v, start_current_a,
       polarity, battery_type, dimensions, terminal_type, weight, features,
       length, width, height, image_url, normalized_name
FROM cleanned.forte_market_batteries
UNION ALL
SELECT source, source_product_id, brand, capacity_ah, voltage_v, start_current_a,
       polarity, battery_type, dimensions, terminal_type, weight, features,
       length, width, height, image_url, normalized_name
FROM cleanned.satu_batteries;

CREATE TABLE master.tmp_batteries_sku_map AS
SELECT s.id AS sku_id, elem->>'id' AS source_product_id, elem->>'source' AS source
FROM master.skus s
CROSS JOIN LATERAL jsonb_array_elements(
    CASE
        WHEN jsonb_typeof(s.source_id) = 'array'  THEN s.source_id
        WHEN jsonb_typeof(s.source_id) = 'string' THEN (s.source_id #>> '{}')::jsonb
        ELSE '[]'::jsonb
    END
) AS elem;

CREATE TABLE master.tmp_batteries_with_sku AS
SELECT u.*, m.sku_id
FROM master.tmp_batteries_union u
JOIN master.tmp_batteries_sku_map m
  ON m.source = u.source AND m.source_product_id = u.source_product_id;

INSERT INTO master.sku_attribute_values (sku_id, attribute_id, attribute, value)
SELECT sku_id, 'main_006', 'capacity_ah', mode() WITHIN GROUP (ORDER BY capacity_ah)::text
FROM master.tmp_batteries_with_sku WHERE capacity_ah IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_032', 'voltage_v', mode() WITHIN GROUP (ORDER BY voltage_v)::text
FROM master.tmp_batteries_with_sku WHERE voltage_v IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_025', 'start_current_a', mode() WITHIN GROUP (ORDER BY start_current_a)::text
FROM master.tmp_batteries_with_sku WHERE start_current_a IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_019', 'polarity', mode() WITHIN GROUP (ORDER BY polarity)
FROM master.tmp_batteries_with_sku WHERE polarity IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_004', 'battery_type', mode() WITHIN GROUP (ORDER BY battery_type)
FROM master.tmp_batteries_with_sku WHERE battery_type IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_009', 'dimensions', mode() WITHIN GROUP (ORDER BY dimensions)
FROM master.tmp_batteries_with_sku WHERE dimensions IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_027', 'terminal_type', mode() WITHIN GROUP (ORDER BY terminal_type)
FROM master.tmp_batteries_with_sku WHERE terminal_type IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_034', 'weight', mode() WITHIN GROUP (ORDER BY weight)
FROM master.tmp_batteries_with_sku WHERE weight IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_011', 'features', mode() WITHIN GROUP (ORDER BY features)
FROM master.tmp_batteries_with_sku WHERE features IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_014', 'length', mode() WITHIN GROUP (ORDER BY length)
FROM master.tmp_batteries_with_sku WHERE length IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_035', 'width', mode() WITHIN GROUP (ORDER BY width)
FROM master.tmp_batteries_with_sku WHERE width IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_013', 'height', mode() WITHIN GROUP (ORDER BY height)
FROM master.tmp_batteries_with_sku WHERE height IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_036', 'image_url', mode() WITHIN GROUP (ORDER BY image_url)
FROM master.tmp_batteries_with_sku WHERE image_url IS NOT NULL GROUP BY sku_id;

DROP TABLE master.tmp_batteries_union;
DROP TABLE master.tmp_batteries_sku_map;
DROP TABLE master.tmp_batteries_with_sku;

--filters
CREATE TABLE master.tmp_filters_union AS
SELECT source, source_product_id, brand, filter_type, compatible_brand,
       compatible_model, oem_number, additional_information, image_url, normalized_name
FROM cleanned.carcity_filters
UNION ALL
SELECT source, source_product_id, brand, filter_type, compatible_brand,
       compatible_model, oem_number, additional_information, image_url, normalized_name
FROM cleanned.forte_market_filters
UNION ALL
SELECT source, source_product_id, brand, filter_type, compatible_brand,
       compatible_model, oem_number, additional_information, image_url, normalized_name
FROM cleanned.satu_filters;

CREATE TABLE master.tmp_filters_sku_map AS
SELECT s.id AS sku_id, elem->>'id' AS source_product_id, elem->>'source' AS source
FROM master.skus s
CROSS JOIN LATERAL jsonb_array_elements(
    CASE
        WHEN jsonb_typeof(s.source_id) = 'array'  THEN s.source_id
        WHEN jsonb_typeof(s.source_id) = 'string' THEN (s.source_id #>> '{}')::jsonb
        ELSE '[]'::jsonb
    END
) AS elem;

CREATE TABLE master.tmp_filters_with_sku AS
SELECT u.*, m.sku_id
FROM master.tmp_filters_union u
JOIN master.tmp_filters_sku_map m
  ON m.source = u.source AND m.source_product_id = u.source_product_id;

INSERT INTO master.sku_attribute_values (sku_id, attribute_id, attribute, value)
SELECT sku_id, 'main_012', 'filter_type', mode() WITHIN GROUP (ORDER BY filter_type)
FROM master.tmp_filters_with_sku WHERE filter_type IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_007', 'compatible_brand', mode() WITHIN GROUP (ORDER BY compatible_brand)
FROM master.tmp_filters_with_sku WHERE compatible_brand IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_008', 'compatible_model', mode() WITHIN GROUP (ORDER BY compatible_model)
FROM master.tmp_filters_with_sku WHERE compatible_model IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_016', 'oem_number', mode() WITHIN GROUP (ORDER BY oem_number)
FROM master.tmp_filters_with_sku WHERE oem_number IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_002', 'additional_information', mode() WITHIN GROUP (ORDER BY additional_information)
FROM master.tmp_filters_with_sku WHERE additional_information IS NOT NULL GROUP BY sku_id
UNION ALL
SELECT sku_id, 'main_036', 'image_url', mode() WITHIN GROUP (ORDER BY image_url)
FROM master.tmp_filters_with_sku WHERE image_url IS NOT NULL GROUP BY sku_id;

DROP TABLE master.tmp_filters_union;
DROP TABLE master.tmp_filters_sku_map;
DROP TABLE master.tmp_filters_with_sku;