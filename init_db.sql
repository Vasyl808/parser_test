-- Database schema for parsers and the shopping-agent MVP.
-- Run this script in Supabase SQL Editor before running parsers or the API.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

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
    stock NUMERIC,
    weighted BOOLEAN,
    section_slug TEXT,
    promotions TEXT,
    shop TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_silpo_products_category ON silpo_products(category_name);
CREATE INDEX IF NOT EXISTS idx_silpo_products_shop ON silpo_products(shop);
CREATE INDEX IF NOT EXISTS idx_silpo_products_is_economy ON silpo_products(is_economy);

CREATE TABLE IF NOT EXISTS atb_products (
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
    shop TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_atb_products_category ON atb_products(category_name);
CREATE INDEX IF NOT EXISTS idx_atb_products_shop ON atb_products(shop);
CREATE INDEX IF NOT EXISTS idx_atb_products_is_economy ON atb_products(is_economy);

-- Unified catalog layer. For MVP it is seeded from ATB only, but the shape is
-- ready for more stores without changing the agent API.
CREATE TABLE IF NOT EXISTS stores (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS canonical_categories (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    parent_id BIGINT REFERENCES canonical_categories(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS category_aliases (
    id BIGSERIAL PRIMARY KEY,
    canonical_category_id BIGINT NOT NULL REFERENCES canonical_categories(id) ON DELETE CASCADE,
    store_id BIGINT NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    raw_category_name TEXT NOT NULL,
    normalized_raw_category_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(store_id, normalized_raw_category_name)
);

CREATE TABLE IF NOT EXISTS store_products (
    id BIGSERIAL PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    store_sku TEXT NOT NULL,
    source_table TEXT NOT NULL DEFAULT 'atb_products',
    name TEXT NOT NULL,
    brand TEXT,
    weight TEXT,
    unit TEXT,
    normalized_name TEXT NOT NULL,
    normalized_brand TEXT,
    normalized_weight NUMERIC,
    normalized_unit TEXT,
    price_per_unit NUMERIC,
    url TEXT,
    current_price NUMERIC,
    regular_price NUMERIC,
    discount TEXT,
    is_promo BOOLEAN NOT NULL DEFAULT FALSE,
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    is_economy BOOLEAN NOT NULL DEFAULT FALSE,
    raw_category_name TEXT,
    canonical_category_id BIGINT REFERENCES canonical_categories(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(store_id, store_sku)
);

CREATE TABLE IF NOT EXISTS canonical_products (
    id BIGSERIAL PRIMARY KEY,
    canonical_key TEXT NOT NULL UNIQUE,
    canonical_name TEXT NOT NULL,
    brand TEXT,
    normalized_name TEXT NOT NULL,
    normalized_brand TEXT,
    normalized_weight NUMERIC,
    normalized_unit TEXT,
    category_id BIGINT REFERENCES canonical_categories(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS product_matches (
    id BIGSERIAL PRIMARY KEY,
    canonical_product_id BIGINT NOT NULL REFERENCES canonical_products(id) ON DELETE CASCADE,
    store_product_id BIGINT NOT NULL REFERENCES store_products(id) ON DELETE CASCADE,
    match_score NUMERIC NOT NULL DEFAULT 1.0,
    match_method TEXT NOT NULL DEFAULT 'same_store_seed',
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(canonical_product_id, store_product_id),
    UNIQUE(store_product_id)
);

CREATE INDEX IF NOT EXISTS idx_category_aliases_store_raw
ON category_aliases(store_id, normalized_raw_category_name);

CREATE INDEX IF NOT EXISTS idx_store_products_name_trgm
ON store_products USING GIN (normalized_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_store_products_brand
ON store_products(normalized_brand);

CREATE INDEX IF NOT EXISTS idx_store_products_category
ON store_products(canonical_category_id);

CREATE INDEX IF NOT EXISTS idx_store_products_store
ON store_products(store_id);

CREATE INDEX IF NOT EXISTS idx_store_products_promo
ON store_products(is_promo, is_economy);

CREATE INDEX IF NOT EXISTS idx_canonical_products_name_trgm
ON canonical_products USING GIN (normalized_name gin_trgm_ops);

CREATE OR REPLACE VIEW shopping_products AS
SELECT
    sp.id AS store_product_id,
    cp.id AS canonical_product_id,
    s.name AS store,
    s.slug AS store_slug,
    sp.store_sku,
    sp.name,
    sp.brand,
    sp.weight,
    sp.unit,
    sp.normalized_name,
    sp.normalized_brand,
    sp.normalized_weight,
    sp.normalized_unit,
    sp.price_per_unit,
    sp.current_price,
    sp.regular_price,
    sp.discount,
    sp.is_promo,
    sp.is_available,
    sp.is_economy,
    sp.raw_category_name,
    cc.name AS canonical_category_name,
    sp.url,
    sp.updated_at,
    pm.match_score,
    pm.match_method,
    pm.is_verified
FROM store_products sp
JOIN stores s ON s.id = sp.store_id
LEFT JOIN canonical_categories cc ON cc.id = sp.canonical_category_id
LEFT JOIN product_matches pm ON pm.store_product_id = sp.id
LEFT JOIN canonical_products cp ON cp.id = pm.canonical_product_id;
