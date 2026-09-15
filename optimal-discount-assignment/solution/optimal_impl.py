#!/usr/bin/env python3
"""
Optimal discount solver using memoized dynamic programming.

Enumerates all possible single-application discount options (including
all integer compositions for cheapest_free_group), then searches the
state space of remaining product quantities to find the minimum-cost
allocation.
"""

from functools import lru_cache


def _get_discount_products(d):
    if "product" in d:
        return [d["product"]]
    if "products" in d:
        return list(d["products"])
    return []


def _generate_compositions(n_products, group_size):
    """Generate all ways to distribute group_size items among n_products slots."""
    results = []

    def backtrack(idx, remaining, current):
        if idx == n_products - 1:
            results.append(tuple(current) + (remaining,))
            return
        for qty in range(remaining + 1):
            backtrack(idx + 1, remaining - qty, current + [qty])

    if n_products > 0 and group_size > 0:
        backtrack(0, group_size, [])
    return results


def _enumerate_options(discounts, catalog, products, prod_index):
    """
    Enumerate all possible single-application discount options.

    Returns list of (items_tuple, cost) where:
      items_tuple: tuple of ints indexed by product position (units consumed)
      cost: what the customer pays for those items under this discount
    """
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
    using DP over the product-quantity state space.
    """
    if not cart or all(v == 0 for v in cart.values()):
        return 0.0

    all_products = set(cart.keys())
    for d in discounts:
        all_products.update(_get_discount_products(d))
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
