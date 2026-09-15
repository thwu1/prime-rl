"""
Supermarket Pricing Engine — Optimal Implementation

Reads product catalog and discount rules from a normalized SQLite database,
enumerates discount application options, and uses memoized dynamic programming
to find the globally minimum total price for any shopping cart.
"""

import sqlite3
from functools import lru_cache


def load_catalog_from_db(db_path="/app/supermarket.db"):
    """Load product catalog from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    catalog = {}
    for row in conn.execute("SELECT product_id, name, unit_price FROM products"):
        catalog[row["product_id"]] = {
            "name": row["name"],
            "unit_price": row["unit_price"],
        }
    conn.close()
    return catalog


def load_discounts_from_db(db_path="/app/supermarket.db"):
    """Reconstruct discount rules from normalized SQLite schema."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    discounts = []

    for row in conn.execute(
        "SELECT discount_id, type, description FROM discounts ORDER BY discount_id"
    ):
        d = {"id": row["discount_id"], "type": row["type"]}

        for p in conn.execute(
            "SELECT param_name, param_value FROM discount_params "
            "WHERE discount_id = ?",
            (d["id"],),
        ):
            name, value = p["param_name"], p["param_value"]
            if name in ("quantity", "buy_count", "free_count", "group_size"):
                d[name] = int(value)
            elif name in ("fixed_price", "percent_off"):
                d[name] = float(value)
            elif name == "max_items":
                d[name] = None if value == "null" else int(value)
            else:
                d[name] = value

        products = [
            r["product_id"]
            for r in conn.execute(
                "SELECT product_id FROM discount_products "
                "WHERE discount_id = ? ORDER BY product_id",
                (d["id"],),
            )
        ]

        if d["type"] in ("multi_buy", "percentage", "buy_n_get_m_free"):
            d["product"] = products[0] if products else None
        elif d["type"] in ("bundle", "cheapest_free_group"):
            d["products"] = products

        if d["type"] == "percentage" and "max_items" not in d:
            d["max_items"] = None

        discounts.append(d)

    conn.close()
    return discounts


def _generate_compositions(n_slots, total):
    """Generate all ways to distribute `total` items across `n_slots`."""
    results = []

    def backtrack(idx, remaining, current):
        if idx == n_slots - 1:
            results.append(tuple(current) + (remaining,))
            return
        for qty in range(remaining + 1):
            backtrack(idx + 1, remaining - qty, current + [qty])

    if n_slots > 0 and total > 0:
        backtrack(0, total, [])
    return results


def _enumerate_options(discounts, catalog, products, prod_index):
    """Enumerate all possible single-application discount options."""
    n = len(products)
    options = []

    for d in discounts:
        dtype = d["type"]

        if dtype == "multi_buy":
            p = d["product"]
            if p in prod_index:
                items = [0] * n
                items[prod_index[p]] = d["quantity"]
                options.append((tuple(items), d["fixed_price"]))

        elif dtype == "percentage":
            p = d["product"]
            if p in prod_index:
                items = [0] * n
                items[prod_index[p]] = 1
                cost = catalog[p]["unit_price"] * (1 - d["percent_off"] / 100)
                options.append((tuple(items), cost))

        elif dtype == "bundle":
            bundle_products = d["products"]
            if all(p in prod_index for p in bundle_products):
                items = [0] * n
                for p in bundle_products:
                    items[prod_index[p]] += 1
                full_cost = sum(catalog[p]["unit_price"] for p in bundle_products)
                cost = full_cost * (1 - d["percent_off"] / 100)
                options.append((tuple(items), cost))

        elif dtype == "buy_n_get_m_free":
            p = d["product"]
            if p in prod_index:
                items = [0] * n
                group_total = d["buy_count"] + d["free_count"]
                items[prod_index[p]] = group_total
                cost = d["buy_count"] * catalog[p]["unit_price"]
                options.append((tuple(items), cost))

        elif dtype == "cheapest_free_group":
            eligible = [p for p in d["products"] if p in prod_index]
            if not eligible:
                continue
            eligible_indices = [prod_index[p] for p in eligible]
            eligible_prices = [catalog[p]["unit_price"] for p in eligible]

            compositions = _generate_compositions(len(eligible), d["group_size"])
            for comp in compositions:
                item_prices = []
                items = [0] * n
                for j, qty in enumerate(comp):
                    if qty > 0:
                        items[eligible_indices[j]] += qty
                        item_prices.extend([eligible_prices[j]] * qty)

                if not item_prices:
                    continue

                cheapest = min(item_prices)
                cost = sum(item_prices) - cheapest
                options.append((tuple(items), cost))

    return options


def calculate_optimal_total(cart, catalog, discounts):
    """
    Calculate the minimum possible total price for the given cart
    by searching the full state space of discount assignments.
    """
    if not cart or all(v == 0 for v in cart.values()):
        return 0.0

    all_products = set(cart.keys())
    for d in discounts:
        if "product" in d and d["product"]:
            all_products.add(d["product"])
        if "products" in d:
            all_products.update(d["products"])
    products = sorted(p for p in all_products if p in catalog)
    prod_index = {p: i for i, p in enumerate(products)}
    prices = tuple(catalog[p]["unit_price"] for p in products)
    n = len(products)

    quantities = tuple(cart.get(p, 0) for p in products)

    options = _enumerate_options(discounts, catalog, products, prod_index)

    @lru_cache(maxsize=None)
    def dp(remaining):
        best = sum(prices[i] * remaining[i] for i in range(n))
        for items_needed, cost in options:
            if all(remaining[i] >= items_needed[i] for i in range(n)):
                new_rem = tuple(remaining[i] - items_needed[i] for i in range(n))
                candidate = cost + dp(new_rem)
                if candidate < best:
                    best = candidate
        return best

    return round(dp(quantities), 2)
