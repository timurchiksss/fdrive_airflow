-- ============================================================================
--  §4.10  Связи categories — часть Madi.
--  Зона ответственности этой части:
--    - PK на categories.category_id (§4.3);
--    - иерархия categories.parent_category_id -> categories;
--    - связи category_attributes -> categories / attribute_groups / attributes.
--  НЕ создаём skus -> categories: этой связью владеет напарник
--    (его ключ skus_category_id_fkey). Старый дубль skus_category_fkey удаляем.
--  Всё идемпотентно (создаём ограничение только если его ещё нет).
-- ============================================================================
SET search_path = master, public;

-- 1) PK на categories (если ещё нет)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname='categories_pkey' AND conrelid='master.categories'::regclass) THEN
    ALTER TABLE master.categories ADD CONSTRAINT categories_pkey PRIMARY KEY (category_id);
  END IF;
END $$;

-- 2) parent_category_id -> bigint (нужно для self-FK), если ещё не bigint
DO $$ BEGIN
  IF (SELECT data_type FROM information_schema.columns
      WHERE table_schema='master' AND table_name='categories'
        AND column_name='parent_category_id') <> 'bigint' THEN
    ALTER TABLE master.categories
      ALTER COLUMN parent_category_id TYPE bigint USING parent_category_id::bigint;
  END IF;
END $$;

-- 3) иерархия categories.parent_category_id -> categories.category_id
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname='categories_parent_fkey' AND conrelid='master.categories'::regclass) THEN
    ALTER TABLE master.categories ADD CONSTRAINT categories_parent_fkey
      FOREIGN KEY (parent_category_id) REFERENCES master.categories(category_id);
  END IF;
END $$;

-- 4) category_attributes.category_id -> categories.category_id
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname='category_attributes_category_fkey' AND conrelid='master.category_attributes'::regclass) THEN
    ALTER TABLE master.category_attributes ADD CONSTRAINT category_attributes_category_fkey
      FOREIGN KEY (category_id) REFERENCES master.categories(category_id);
  END IF;
END $$;

-- 5) category_attributes.attribute_group_id -> attribute_groups.id
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname='category_attributes_group_fkey' AND conrelid='master.category_attributes'::regclass) THEN
    ALTER TABLE master.category_attributes ADD CONSTRAINT category_attributes_group_fkey
      FOREIGN KEY (attribute_group_id) REFERENCES master.attribute_groups(id);
  END IF;
END $$;

-- 6) category_attributes.attribute_id -> attributes.id
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname='category_attributes_attribute_id_fkey' AND conrelid='master.category_attributes'::regclass) THEN
    ALTER TABLE master.category_attributes ADD CONSTRAINT category_attributes_attribute_id_fkey
      FOREIGN KEY (attribute_id) REFERENCES master.attributes(id);
  END IF;
END $$;

-- 7) убрать собственный дубль-ключ skus->categories (эту связь ведёт напарник)
ALTER TABLE master.skus DROP CONSTRAINT IF EXISTS skus_category_fkey;
