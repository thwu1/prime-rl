#!/usr/bin/env python3
"""CLI entry point for the supermarket pricing engine."""

import json
import sys
from pricing_engine import load_catalog_from_db, load_discounts_from_db, calculate_optimal_total


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 main.py '<cart_json>'")
        print('Example: python3 main.py \'{"TOOTH_BRUSH": 3, "SOAP": 6}\'')
        sys.exit(1)

    cart = json.loads(sys.argv[1])
    catalog = load_catalog_from_db()
    discounts = load_discounts_from_db()

    full_price = sum(catalog[p]["unit_price"] * q for p, q in cart.items()
                     if p in catalog)
    optimal = calculate_optimal_total(cart, catalog, discounts)

    print(f"Full price:    ${full_price:.2f}")
    print(f"Optimal total: ${optimal:.2f}")
    print(f"You save:      ${full_price - optimal:.2f}")


if __name__ == "__main__":
    main()
