#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для перевірки підключення до Supabase API
"""
import os
import sys
from dotenv import load_dotenv

# Завантаження змінних середовища
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

print("=" * 60)
print("  Перірка підключення до Supabase API")
print("=" * 60)

# Перевірка наявності змінних середовища
print("\n[1] Перевірка змінних середовища...")
missing_vars = []

if not SUPABASE_URL:
    missing_vars.append("SUPABASE_URL")
    print("  ❌ SUPABASE_URL не встановлено")
else:
    print("  ✓ SUPABASE_URL встановлено")

if not SUPABASE_KEY:
    missing_vars.append("SUPABASE_KEY")
    print("  ❌ SUPABASE_KEY не встановлено")
else:
    print("  ✓ SUPABASE_KEY встановлено")

if missing_vars:
    print(f"\n❌ Відсутні змінні: {', '.join(missing_vars)}")
    print("Будь ласка, встановіть їх у .env файлі або GitHub Secrets")
    sys.exit(1)

# Перевірка підключення до Supabase API
print("\n[2] Перевірка підключення до Supabase API...")
try:
    from supabase import create_client
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Спроба виконати простий запит
    response = client.table("silpo_products").select("sku", count="exact").execute()
    print("  ✓ Підключення до Supabase API успішне")
    print(f"  Кількість записів в таблиці silpo_products: {response.count}")
except Exception as e:
    print(f"  ❌ Помилка підключення до Supabase API: {e}")
    print("  Примітка: Таблиця silpo_products може ще не існувати")
    print("  Створіть її виконавши init_db.sql в Supabase SQL Editor")
    sys.exit(1)

print("\n" + "=" * 60)
print("  Всі перевірки пройдено успішно!")
print("=" * 60)
