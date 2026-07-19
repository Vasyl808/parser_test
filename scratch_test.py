import asyncio
import os
import json
from shopping_agent.repository import ProductRepository
from shopping_agent.config import Settings
from dotenv import load_dotenv

load_dotenv()

async def main():
    settings = Settings.from_env()
    repo = ProductRepository.from_settings(settings)
    
    response = repo.client.table("shopping_products").select("name, raw_category_name, canonical_category_name").ilike("name", "%молоко%").limit(20).execute()
    
    with open("d:/parser_store/debug_categories.json", "w", encoding="utf-8") as f:
        json.dump(response.data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
