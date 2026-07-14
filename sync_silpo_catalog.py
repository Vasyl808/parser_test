#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed the unified catalog from the existing silpo_products table."""

from unified_catalog import sync_existing_silpo_products


def main() -> None:
    stats = sync_existing_silpo_products()
    print("=" * 60)
    print("Silpo unified catalog sync complete")
    print("=" * 60)
    for key, value in stats.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
