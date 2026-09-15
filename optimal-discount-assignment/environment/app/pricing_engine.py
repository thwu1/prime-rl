"""
Supermarket Pricing Engine

This module implements discount calculation for a supermarket receipt system.
Product catalog and discount rules are stored in a normalized SQLite database
(supermarket.db). The database has four tables:

  products:          product_id (PK), name, unit_price
  discounts:         discount_id (PK), type, description
  discount_params:   discount_id (FK), param_name, param_value — composite PK
  discount_products: discount_id (FK), product_id (FK), role — composite PK

Required functions:
  load_catalog_from_db(db_path): Return dict of product_id -> {name, unit_price}
  load_discounts_from_db(db_path): Reconstruct discount rule dicts from the
      normalized schema. Each dict must have at minimum 'id', 'type', and the
      type-specific fields listed below.

  calculate_optimal_total(cart, catalog, discounts): Return the minimum possible
      total price. Must use GLPK (glpsol) with a GMPL model file (model.mod)
      to solve the discount assignment as a Mixed Integer Linear Program.

Discount types:
  multi_buy:
    Fields: product (str), quantity (int), fixed_price (float)
    Buy exactly `quantity` units of `product` for a flat `fixed_price`.
    Repeatable.

  percentage:
    Fields: product (str), percent_off (float), max_items (int or None)
    Each unit of `product` is charged at unit_price * (1 - percent_off/100).
    `max_items` caps how many units receive the discount; None = unlimited.

  bundle:
    Fields: products (list[str]), percent_off (float)
    Buy one unit of every product in `products` and pay
    sum(unit_prices) * (1 - percent_off/100). Repeatable.

  buy_n_get_m_free:
    Fields: product (str), buy_count (int), free_count (int)
    Every group of (buy_count + free_count) units costs
    buy_count * unit_price. Repeatable.

  cheapest_free_group:
    Fields: products (list[str]), group_size (int)
    Pick `group_size` items from eligible `products` (any mix).
    The single cheapest item in the group is free. Repeatable.

Constraints:
  - Each physical unit participates in at most one discount application.
  - Unassigned units are charged at full catalog price.
  - Final total: round(total, 2).
"""

import sqlite3


def load_catalog_from_db(db_path="/app/supermarket.db"):
    """Load product catalog from SQLite. Returns {product_id: {name, unit_price}}."""
    raise NotImplementedError("Must query the products table")


def load_discounts_from_db(db_path="/app/supermarket.db"):
    """Reconstruct discount rules from normalized schema. Returns list of dicts."""
    raise NotImplementedError("Must JOIN discounts, discount_params, discount_products")


def _greedy_total(cart, catalog, discounts):
    """
    Greedy discount application: processes discounts in declaration order,
    applying each as many times as possible before moving to the next.
    This often produces suboptimal results because early discount applications
    lock items away from potentially more profitable later discounts.
    """
    remaining = dict(cart)
    total = 0.0

    for d in discounts:
        if d["type"] == "multi_buy":
            p = d["product"]
            while remaining.get(p, 0) >= d["quantity"]:
                remaining[p] -= d["quantity"]
                total += d["fixed_price"]

        elif d["type"] == "percentage":
            p = d["product"]
            qty = remaining.get(p, 0)
            if d.get("max_items") is not None:
                qty = min(qty, d["max_items"])
            total += qty * catalog[p]["unit_price"] * (1 - d["percent_off"] / 100)
            remaining[p] = remaining.get(p, 0) - qty

        elif d["type"] == "bundle":
            while all(remaining.get(p, 0) >= 1 for p in d["products"]):
                bundle_full = sum(catalog[p]["unit_price"] for p in d["products"])
                total += bundle_full * (1 - d["percent_off"] / 100)
                for p in d["products"]:
                    remaining[p] -= 1

        elif d["type"] == "buy_n_get_m_free":
            p = d["product"]
            group = d["buy_count"] + d["free_count"]
            while remaining.get(p, 0) >= group:
                remaining[p] -= group
                total += d["buy_count"] * catalog[p]["unit_price"]

        elif d["type"] == "cheapest_free_group":
            while True:
                available = []
                for p in d["products"]:
                    for _ in range(remaining.get(p, 0)):
                        available.append((p, catalog[p]["unit_price"]))
                available.sort(key=lambda x: -x[1])

                if len(available) < d["group_size"]:
                    break

                group = available[: d["group_size"]]
                cheapest_price = min(price for _, price in group)
                total += sum(price for _, price in group) - cheapest_price

                for p, _ in group:
                    remaining[p] -= 1

    for p, qty in remaining.items():
        if qty > 0:
            total += qty * catalog[p]["unit_price"]

    return round(total, 2)


def calculate_optimal_total(cart, catalog, discounts):
    """
    Calculate the minimum possible total price for the given cart.

    Args:
        cart: dict mapping product_id (str) -> quantity (int, >= 0)
        catalog: dict mapping product_id -> {"name": str, "unit_price": float}
        discounts: list of discount rule dicts (see module docstring)

    Returns:
        float: minimum total price, rounded to 2 decimal places
    """
    return _greedy_total(cart, catalog, discounts)
