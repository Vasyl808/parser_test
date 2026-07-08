# Silpo Parser + Supabase + GitHub Actions

Цей проект автоматично парсить дані з Silpo через JSON API і зберігає їх в Supabase базу даних. Скрипт запускається щотижня через GitHub Actions.

## Особливості

- **Автоматичне створення таблиці**: База даних ініціалізується автоматично при першому запуску
- **Batch upsert**: Дані оновлюються пачками по 1000 записів для оптимальної продуктивності
- **Upsert по SKU**: Існуючі записи оновлюються, нові - додаються
- **Безкоштовно**: Використовує GitHub Actions і Supabase Free Tier

## Налаштування Supabase

### 1. Створення проекту Supabase

1. Перейдіть на [supabase.com](https://supabase.com) і створіть безкоштовний акаунт
2. Натисніть "New Project"
3. Введіть назву проекту (наприклад, `silpo-parser`)
4. Зберігте пароль бази даних (він знадобиться для connection string)
5. Чекайте завершення створення проекту (1-2 хвилини)

### 2. Отримання credential

#### SUPABASE_URL та SUPABASE_KEY (для SDK)

1. У вашому проекті Supabase перейдіть в **Settings** → **API**
2. Скопіюйте **Project URL** → це `SUPABASE_URL`
3. Скопіюйте **service_role key** (або `anon` key, якщо service_role недоступний) → це `SUPABASE_KEY`
   - **Важно**: Використовуйте `service_role key` для повного доступу до запису

## Налаштування GitHub Secrets

1. Перейдіть в ваш GitHub репозиторій
2. Натисніть **Settings** → **Secrets and variables** → **Actions**
3. Натисніть **New repository secret** і додайте два секрети:

   - **Name**: `SUPABASE_URL`
     **Value**: ваш Project URL (з кроку 2)

   - **Name**: `SUPABASE_KEY`
     **Value**: ваш service_role key (з кроку 2)

4. Натисніть **Add secret** для кожного

## Створення таблиці в Supabase

Перед першим запуском потрібно створити таблицю в Supabase:

1. У вашому проекті Supabase перейдіть в **SQL Editor**
2. Натисніть **New Query**
3. Скопіюйте вміст файлу `init_db.sql` і вставте в редактор
4. Натисніть **Run** для виконання SQL скрипта
5. Таблиця `silpo_products` буде створена з необхідними полями та індексами

## Локальний запуск

Для тестування скрипта локально:

```bash
# Встановлення залежностей
pip install -r requirements.txt

# Копіюйте приклад .env файлу і заповніть свої дані
cp .env.example .env

# Редагуйте .env файл та вставте свої credential
# SUPABASE_URL=https://your-project.supabase.co
# SUPABASE_KEY=your-service-role-key

# Запустіть скрипт (python-dotenv автоматично завантажить змінні з .env)
python silpo_api_parser.py
```

## Структура бази даних

Таблиця `silpo_products` створюється автоматично з такими полями:

| Поле | Тип | Опис |
|------|-----|------|
| sku | TEXT (PK) | Унікальний ідентифікатор товару |
| name | TEXT | Назва товару |
| brand | TEXT | Бренд |
| weight | TEXT | Вага |
| unit | TEXT | Одиниця виміру |
| url | TEXT | URL товару |
| current_price | NUMERIC | Поточна ціна |
| regular_price | NUMERIC | Звичайна ціна |
| discount | TEXT | Знижка у % |
| is_promo | BOOLEAN | Чи є акція |
| is_available | BOOLEAN | Чи є в наявності |
| is_economy | BOOLEAN | Чи є "Ціна тижня" |
| category_name | TEXT | Назва категорії |
| category_url | TEXT | URL категорії |
| bulk_price | NUMERIC | Ціна за опт |
| bulk_qty | INTEGER | Оптова кількість |
| rating | NUMERIC | Рейтинг |
| rating_count | INTEGER | Кількість оцінок |
| stock | INTEGER | Кількість на складі |
| weighted | BOOLEAN | Ваговий товар |
| section_slug | TEXT | Slug секції |
| promotions | TEXT | Список акцій |
| shop | TEXT | Магазин (silpo) |
| updated_at | TIMESTAMP | Час оновлення |

## Запуск workflow

### Автоматичний запуск

Workflow запускається автоматично щонеділі о 00:00 UTC за розкладом:
```yaml
cron: '0 0 * * 0'
```

### Ручний запуск

1. Перейдіть в **Actions** tab у вашому репозиторії
2. Виберіть workflow **Silpo Parser**
3. Натисніть **Run workflow** → **Run workflow**

### Зміна розкладу

Щоб змінити частоту запуску, відредагуйте файл `.github/workflows/silpo-parser.yml`:

```yaml
schedule:
  # Щодня о 00:00 UTC
  - cron: '0 0 * * *'
  
  # Щоп'ятниці о 18:00 UTC
  - cron: '0 18 * * 5'
  
  # Кожного місяця 1-го числа о 00:00 UTC
  - cron: '0 0 1 * *'
```

## Моніторинг

Після запуску workflow ви можете побачити логи в **Actions** tab. Скрипт виводить:

- Кількість знайдених категорій
- Прогрес парсингу по категоріях
- Кількість унікальних товарів
- Кількість "Цінотижків"
- Інформацію про batch upsert operations

## Вирішення проблем

### Помилка "DATABASE_URL environment variable is not set"
Перевірте, що ви додали `DATABASE_URL` в GitHub Secrets.

### Помилка "SUPABASE_URL and SUPABASE_KEY environment variables must be set"
Перевірте, що ви додали `SUPABASE_URL` і `SUPABASE_KEY` в GitHub Secrets.

### Помилка підключення до бази даних
Перевірте, що connection string правильний і пароль вірний. Якщо пароль містить спецсимволи, переконайтеся, що вони правильно URL-encoded.

### Помилка upsert
Переконайтеся, що використовуєте `service_role key` замість `anon key` для повного доступу до запису.

## Ліцензія

MIT
