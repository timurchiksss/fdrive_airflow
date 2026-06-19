-- ============================================================
-- Сборка matching.sku_price_history из cleanned.* (14 таблиц)
-- ============================================================

-- 1) ЦЕЛЕВАЯ ТАБЛИЦА (зона A) -------------------------------
DROP TABLE IF EXISTS matching.sku_price_history;
CREATE TABLE matching.sku_price_history (
  captured_at       timestamptz,   -- момент среза парсинга (= loaded_at загрузки)
  price_date        date,          -- captured_at::date, для дневной аналитики
  sku_id            text,
  source            text,
  source_product_id text,
  seller_name       text,
  city              text,
  price             double precision,
  old_price         double precision,
  discount_price    double precision,
  currency          text,
  availability      text,
  parsed_at         timestamptz,   -- момент парсинга товара
  CONSTRAINT uq_sph UNIQUE (source, source_product_id, captured_at)
);
CREATE INDEX ix_sph_sku  ON matching.sku_price_history (sku_id);
CREATE INDEX ix_sph_date ON matching.sku_price_history (price_date);
CREATE INDEX ix_sph_cap  ON matching.sku_price_history (source, source_product_id, captured_at);

-- 2) СТЕЙДЖИНГ — UNION ALL по 14 таблицам (зона B) ----------
--    Генерируем тело view динамически из каталога, чтобы не писать 14 раз.
DROP VIEW IF EXISTS matching.stg_price_history;
SELECT 'CREATE VIEW matching.stg_price_history AS ' || string_agg(
  format($f$
SELECT
  loaded_at                                           AS captured_at,
  loaded_at::date                                     AS price_date,
  source,
  source_product_id,
  source                                              AS seller_name,
  city, price, old_price,
  CASE WHEN old_price > price THEN price END          AS discount_price,
  currency, availability,
  COALESCE(NULLIF(parsed_at,'')::timestamptz, loaded_at) AS parsed_at
FROM cleanned.%I$f$, table_name), E'\nUNION ALL\n')
FROM information_schema.tables
WHERE table_schema='cleanned'
\gexec

-- 3) МАТЧИНГ + ЗАЛИВКА (зона C + upsert зоны A) -------------
WITH map AS (   -- дедуп маппинга: лучший sku_id по ключу
  SELECT DISTINCT ON (source, source_product_id)
         source, source_product_id, sku_id
  FROM matching.sku_source_mapping
  ORDER BY source, source_product_id, match_score DESC NULLS LAST
)
INSERT INTO matching.sku_price_history
  (captured_at, price_date, sku_id, source, source_product_id, seller_name,
   city, price, old_price, discount_price, currency, availability, parsed_at)
SELECT DISTINCT ON (s.source, s.source_product_id, s.captured_at)
       s.captured_at, s.price_date, m.sku_id, s.source, s.source_product_id, s.seller_name,
       s.city, s.price, s.old_price, s.discount_price, s.currency, s.availability, s.parsed_at
FROM matching.stg_price_history s
LEFT JOIN map m USING (source, source_product_id)
WHERE s.price IS NOT NULL                 -- строки без цены в историю не берём
ORDER BY s.source, s.source_product_id, s.captured_at
ON CONFLICT (source, source_product_id, captured_at) DO UPDATE
  SET price          = EXCLUDED.price,
      old_price      = EXCLUDED.old_price,
      discount_price = EXCLUDED.discount_price,
      availability   = EXCLUDED.availability,
      sku_id         = EXCLUDED.sku_id,
      parsed_at      = EXCLUDED.parsed_at;
