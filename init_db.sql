-- Створення таблиці silpo_products для парсера Silpo
-- Виконайте цей скрипт в Supabase SQL Editor: https://app.supabase.com/project/[your-project]/sql/new

CREATE TABLE IF NOT EXISTS silpo_products (
    sku TEXT PRIMARY KEY,
    name TEXT,
    brand TEXT,
    weight TEXT,
    unit TEXT,
    url TEXT,
    current_price NUMERIC,
    regular_price NUMERIC,
    discount TEXT,
    is_promo BOOLEAN,
    is_available BOOLEAN,
    is_economy BOOLEAN,
    category_name TEXT,
    category_url TEXT,
    bulk_price NUMERIC,
    bulk_qty INTEGER,
    rating NUMERIC,
    rating_count INTEGER,
    stock INTEGER,
    weighted BOOLEAN,
    section_slug TEXT,
    promotions TEXT,
    shop TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Опціонально: створення індексів для кращої продуктивності
CREATE INDEX IF NOT EXISTS idx_silpo_products_category ON silpo_products(category_name);
CREATE INDEX IF NOT EXISTS idx_silpo_products_shop ON silpo_products(shop);
CREATE INDEX IF NOT EXISTS idx_silpo_products_is_economy ON silpo_products(is_economy);
