-- Корисні SQL запити для перевірки даних в Supabase
-- Виконуйте в Supabase SQL Editor

-- 1. Загальна кількість товарів
SELECT COUNT(*) as total_products FROM silpo_products;

-- 2. Кількість "Цінотижків" (is_economy = true)
SELECT COUNT(*) as economy_products FROM silpo_products WHERE is_economy = true;

-- 3. Кількість акційних товарів (is_promo = true)
SELECT COUNT(*) as promo_products FROM silpo_products WHERE is_promo = true;

-- 4. Товари в наявності (is_available = true)
SELECT COUNT(*) as available_products FROM silpo_products WHERE is_available = true;

-- 5. Топ-10 категорій за кількістю товарів
SELECT category_name, COUNT(*) as product_count 
FROM silpo_products 
GROUP BY category_name 
ORDER BY product_count DESC 
LIMIT 10;

-- 6. Середня ціна по категоріях
SELECT 
    category_name, 
    COUNT(*) as product_count,
    AVG(current_price) as avg_price,
    MIN(current_price) as min_price,
    MAX(current_price) as max_price
FROM silpo_products 
WHERE current_price IS NOT NULL
GROUP BY category_name 
ORDER BY avg_price DESC;

-- 7. Товари з найбільшою знижкою
SELECT 
    name, 
    current_price, 
    regular_price, 
    discount,
    category_name
FROM silpo_products 
WHERE discount IS NOT NULL AND discount != ''
ORDER BY CAST(discount AS INTEGER) DESC
LIMIT 10;

-- 8. Останні 10 оновлених товарів
SELECT 
    sku, 
    name, 
    current_price, 
    updated_at
FROM silpo_products 
ORDER BY updated_at DESC 
LIMIT 10;

-- 9. Перевірка дублікатів (має бути 0)
SELECT sku, COUNT(*) as count 
FROM silpo_products 
GROUP BY sku 
HAVING COUNT(*) > 1;

-- 10. Статистика по магазинах
SELECT 
    shop, 
    COUNT(*) as product_count,
    COUNT(DISTINCT category_name) as category_count
FROM silpo_products 
GROUP BY shop;

-- 11. Товари з рейтингом
SELECT 
    name, 
    rating, 
    rating_count,
    current_price,
    category_name
FROM silpo_products 
WHERE rating IS NOT NULL AND rating > 0
ORDER BY rating DESC 
LIMIT 10;

-- 12. Пошук товару за назвою (замініть 'хліб' на потрібне слово)
SELECT * FROM silpo_products 
WHERE name ILIKE '%хліб%' 
LIMIT 10;

-- 13. Товари в діапазоні цін (наприклад, від 50 до 100 грн)
SELECT 
    name, 
    current_price, 
    category_name,
    url
FROM silpo_products 
WHERE current_price BETWEEN 50 AND 100
ORDER BY current_price
LIMIT 20;

-- 14. Час останнього оновлення даних
SELECT MAX(updated_at) as last_update FROM silpo_products;

-- 15. Вагові товари (weighted = true)
SELECT 
    name, 
    weight, 
    unit, 
    current_price,
    category_name
FROM silpo_products 
WHERE weighted = true
LIMIT 10;
