#!/usr/bin/env python3
"""Run a standard marketplace scenario for demonstration and manual testing.

"""

from models import Item
from legacy_system import LegacyMarketplace


def main():
    mp = LegacyMarketplace()

    mp.load_catalog({
        "+5 Dexterity Vest": 10.00,
        "Aged Brie": 15.00,
        "Sulfuras, Hand of Ragnaros": 999.99,
        "Backstage passes": 25.00,
        "Fresh Salmon": 8.00,
        "Conjured Mana Cake": 5.00,
        "Toothbrush": 0.99,
        "Toothpaste": 1.79,
        "Milk": 3.50,
    })

    mp.set_items([
        Item("+5 Dexterity Vest", "Normal", 10, 20),
        Item("Aged Brie", "Aged", 2, 0),
        Item("Sulfuras, Hand of Ragnaros", "Legendary", 0, 80),
        Item("Backstage passes", "Backstage Pass", 15, 20),
        Item("Fresh Salmon", "Perishable", 3, 15),
        Item("Conjured Mana Cake", "Conjured", 5, 10),
    ])

    mp.set_offers([
        ("PercentOff", "Aged Brie", 10),
        ("BuyNGetFree", "Toothbrush", 2),
        ("FlatDiscount", None, 20.0),
    ])

    cart = [
        ("Toothbrush", 4),
        ("Toothpaste", 2),
        ("Milk", 1),
        ("Aged Brie", 1),
    ]

    print("=== MARKETPLACE SIMULATION ===")
    print()

    for day in range(10):
        print("--- Day {} ---".format(day))
        print("Inventory:")
        print(mp.get_inventory_report())
        mp.update_quality()
        print()

        receipt = mp.process_cart(cart)
        print(mp.format_receipt_text(receipt))
        print()

    # Demonstrate state persistence
    print("=== STATE PERSISTENCE ===")
    state_json = mp.save_state()
    print("Saved state ({} bytes)".format(len(state_json)))

    mp2 = LegacyMarketplace()
    mp2.load_state(state_json)
    print("Loaded state successfully")
    print("Inventory after load:")
    print(mp2.get_inventory_report())


if __name__ == "__main__":
    main()
