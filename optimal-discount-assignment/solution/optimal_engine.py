"""
Supermarket Pricing Engine — MILP Pipeline

Reads product catalog and discount rules from a normalized SQLite database,
formulates the discount assignment problem as a Mixed Integer Linear Program,
solves it using GLPK (glpsol) with a GMPL model, and returns the optimal total.
"""

import os
import re
import sqlite3
import subprocess
import tempfile


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
    """Enumerate all single-application discount options as (items, cost)."""
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
            eligible = d["products"]
            if all(p in prod_index for p in eligible):
                items = [0] * n
                for p in eligible:
                    items[prod_index[p]] += 1
                full = sum(catalog[p]["unit_price"] for p in eligible)
                options.append((tuple(items), full * (1 - d["percent_off"] / 100)))

        elif dtype == "buy_n_get_m_free":
            p = d["product"]
            if p in prod_index:
                items = [0] * n
                items[prod_index[p]] = d["buy_count"] + d["free_count"]
                options.append(
                    (tuple(items), d["buy_count"] * catalog[p]["unit_price"])
                )

        elif dtype == "cheapest_free_group":
            eligible = [p for p in d["products"] if p in prod_index]
            if not eligible:
                continue
            e_idx = [prod_index[p] for p in eligible]
            e_prices = [catalog[p]["unit_price"] for p in eligible]

            for comp in _generate_compositions(len(eligible), d["group_size"]):
                prices_in_group = []
                items = [0] * n
                for j, qty in enumerate(comp):
                    if qty > 0:
                        items[e_idx[j]] += qty
                        prices_in_group.extend([e_prices[j]] * qty)
                if not prices_in_group:
                    continue
                cheapest = min(prices_in_group)
                options.append(
                    (tuple(items), sum(prices_in_group) - cheapest)
                )

    return options


def _write_dat(products, options, cart, catalog, path):
    """Write a GLPK-format .dat file for the GMPL model."""
    n = len(products)

    with open(path, "w") as f:
        f.write("set PRODUCTS :=")
        for p in products:
            f.write(f" {p}")
        f.write(";\n\n")

        if options:
            f.write("set OPTIONS :=")
            for i in range(len(options)):
                f.write(f" O{i}")
            f.write(";\n\n")
        else:
            f.write("set OPTIONS :=;\n\n")

        f.write("param price :=\n")
        for p in products:
            f.write(f"  {p} {catalog[p]['unit_price']:.2f}\n")
        f.write(";\n\n")

        f.write("param qty :=\n")
        for p in products:
            f.write(f"  {p} {cart.get(p, 0)}\n")
        f.write(";\n\n")

        if options:
            f.write("param consume :\n")
            f.write("          " + " ".join(products) + " :=\n")
            for i, (items, _) in enumerate(options):
                f.write(f"  O{i}")
                for j in range(n):
                    f.write(f" {items[j]}")
                f.write("\n")
            f.write(";\n\n")

            f.write("param cost :=\n")
            for i, (_, c) in enumerate(options):
                f.write(f"  O{i} {c:.10f}\n")
            f.write(";\n\n")


def calculate_optimal_total(cart, catalog, discounts):
    """
    Calculate minimum total price via GLPK MILP solver.

    Enumerates discount application options, generates a GMPL data file,
    invokes glpsol with model.mod, and parses the optimal total.
    """
    if not cart or all(v == 0 for v in cart.values()):
        return 0.0

    all_prods = set(cart.keys())
    for d in discounts:
        if "product" in d and d["product"]:
            all_prods.add(d["product"])
        if "products" in d:
            all_prods.update(d["products"])
    products = sorted(p for p in all_prods if p in catalog)
    prod_index = {p: i for i, p in enumerate(products)}

    options = _enumerate_options(discounts, catalog, products, prod_index)
    model_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "model.mod"
    )

    fd, dat_path = tempfile.mkstemp(suffix=".dat")
    os.close(fd)
    try:
        _write_dat(products, options, cart, catalog, dat_path)

        result = subprocess.run(
            ["glpsol", "--model", model_path, "--data", dat_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"glpsol failed:\n{result.stderr}\n{result.stdout}"
            )

        match = re.search(r"OPTIMAL_TOTAL=([\d.]+)", result.stdout)
        if not match:
            raise RuntimeError(
                f"Cannot parse glpsol output:\n{result.stdout}"
            )

        return round(float(match.group(1)), 2)
    finally:
        if os.path.exists(dat_path):
            os.unlink(dat_path)
