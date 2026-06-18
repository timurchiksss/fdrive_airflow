
DROP TABLE IF EXISTS master.sku_price_history;
CREATE TABLE master.sku_price_history (
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
  parsed_at         timestamptz,   -- момент парсинга товара (заполнен только forte)
  loaded_at         timestamptz DEFAULT now(),
  CONSTRAINT uq_sph UNIQUE (source, source_product_id, captured_at)
);
CREATE INDEX ix_sph_sku  ON master.sku_price_history (sku_id);
CREATE INDEX ix_sph_date ON master.sku_price_history (price_date);
CREATE INDEX ix_sph_cap  ON master.sku_price_history (source, source_product_id, captured_at);

--    генерируем тело view динамически из каталога
DROP VIEW IF EXISTS master.stg_price_history;
SELECT 'CREATE VIEW master.stg_price_history AS ' || string_agg(
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
  NULLIF(parsed_at,'')::timestamptz                   AS parsed_at,
  loaded_at
FROM cleanned.%I$f$, table_name), E'\nUNION ALL\n')
FROM information_schema.tables
WHERE table_schema='cleanned'
\gexec

WITH map AS (
  SELECT DISTINCT ON (source, source_product_id)
         source, source_product_id, sku_id
  FROM master.sku_source_mapping
  ORDER BY source, source_product_id, match_score DESC NULLS LAST
)
INSERT INTO master.sku_price_history
  (captured_at, price_date, sku_id, source, source_product_id, seller_name,
   city, price, old_price, discount_price, currency, availability, parsed_at)
SELECT DISTINCT ON (s.source, s.source_product_id, s.captured_at)
       s.captured_at, s.price_date, m.sku_id, s.source, s.source_product_id, s.seller_name,
       s.city, s.price, s.old_price, s.discount_price, s.currency, s.availability, s.parsed_at
FROM master.stg_price_history s
LEFT JOIN map m USING (source, source_product_id)
WHERE s.price IS NOT NULL              
ORDER BY s.source, s.source_product_id, s.captured_at
ON CONFLICT (source, source_product_id, captured_at) DO UPDATE
  SET price          = EXCLUDED.price,
      old_price      = EXCLUDED.old_price,
      discount_price = EXCLUDED.discount_price,
      availability   = EXCLUDED.availability,
      sku_id         = EXCLUDED.sku_id,
      loaded_at      = now();

ALTER TABLE master.sku_price_history
  ADD CONSTRAINT sku_price_history_sku_id_fkey
  FOREIGN KEY (sku_id) REFERENCES master.skus (id);
