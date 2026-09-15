"""
Tests for the supermarket pricing engine optimization pipeline.

Verifies database integration (SQLite data access, discount reconstruction)
and correctness of optimal discount assignment.
Expected optimal totals were computed by exhaustive analysis.
"""

import os
import sys

sys.path.insert(0, "/app")

from pricing_engine import calculate_optimal_total


CATALOG = {
    "TOOTH_BRUSH": {"name": "Toothbrush", "unit_price": 1.99},
    "TOOTH_PASTE": {"name": "Toothpaste", "unit_price": 3.49},
    "MOUTH_WASH": {"name": "Mouthwash", "unit_price": 5.99},
    "DENTAL_FLOSS": {"name": "Dental Floss", "unit_price": 2.29},
    "SHAMPOO": {"name": "Shampoo", "unit_price": 4.99},
    "CONDITIONER": {"name": "Conditioner", "unit_price": 4.99},
    "SOAP": {"name": "Bar Soap", "unit_price": 1.49},
    "RICE": {"name": "Rice (1kg bag)", "unit_price": 2.49},
    "APPLE_JUICE": {"name": "Apple Juice", "unit_price": 2.99},
    "MILK": {"name": "Milk", "unit_price": 1.29},
}

DISCOUNTS = [
    {"id": "D1", "type": "multi_buy", "product": "TOOTH_BRUSH",
     "quantity": 3, "fixed_price": 5.00},
    {"id": "D2", "type": "percentage", "product": "TOOTH_PASTE",
     "percent_off": 20, "max_items": None},
    {"id": "D3", "type": "bundle",
     "products": ["TOOTH_BRUSH", "TOOTH_PASTE", "MOUTH_WASH"], "percent_off": 25},
    {"id": "D4", "type": "bundle",
     "products": ["SHAMPOO", "CONDITIONER"], "percent_off": 30},
    {"id": "D5", "type": "buy_n_get_m_free", "product": "SOAP",
     "buy_count": 2, "free_count": 1},
    {"id": "D6", "type": "percentage", "product": "RICE",
     "percent_off": 10, "max_items": None},
    {"id": "D7", "type": "cheapest_free_group",
     "products": ["TOOTH_BRUSH", "TOOTH_PASTE", "DENTAL_FLOSS", "MOUTH_WASH"],
     "group_size": 3},
    {"id": "D8", "type": "multi_buy", "product": "MILK",
     "quantity": 2, "fixed_price": 2.00},
]


class TestDatabaseIntegration:
    """Verify data access and discount reconstruction from normalized SQLite schema."""

    def test_engine_uses_sqlite(self):
        """The pricing engine must use sqlite3 for data access."""
        with open("/app/pricing_engine.py") as f:
            src = f.read()
        assert "sqlite3" in src, \
            "pricing_engine.py does not import sqlite3"

    def test_load_catalog_from_db(self):
        from pricing_engine import load_catalog_from_db
        catalog = load_catalog_from_db("/app/supermarket.db")
        assert isinstance(catalog, dict)
        assert len(catalog) == 10
        assert "TOOTH_BRUSH" in catalog
        assert catalog["TOOTH_BRUSH"]["unit_price"] == 1.99
        assert catalog["MILK"]["unit_price"] == 1.29

    def test_load_discounts_count(self):
        from pricing_engine import load_discounts_from_db
        discounts = load_discounts_from_db("/app/supermarket.db")
        assert isinstance(discounts, list)
        assert len(discounts) == 8

    def test_load_multi_buy_discount(self):
        """Verify multi_buy params are correctly typed from discount_params."""
        from pricing_engine import load_discounts_from_db
        discounts = load_discounts_from_db("/app/supermarket.db")
        d1 = next(d for d in discounts if d["id"] == "D1")
        assert d1["type"] == "multi_buy"
        assert d1["product"] == "TOOTH_BRUSH"
        assert d1["quantity"] == 3
        assert d1["fixed_price"] == 5.0

    def test_load_cheapest_free_group_discount(self):
        """Verify cheapest_free_group products reconstructed from junction table."""
        from pricing_engine import load_discounts_from_db
        discounts = load_discounts_from_db("/app/supermarket.db")
        d7 = next(d for d in discounts if d["id"] == "D7")
        assert d7["type"] == "cheapest_free_group"
        assert d7["group_size"] == 3
        assert set(d7["products"]) == {
            "TOOTH_BRUSH", "TOOTH_PASTE", "DENTAL_FLOSS", "MOUTH_WASH"
        }

    def test_load_bundle_discount(self):
        """Verify bundle products and percent_off from normalized schema."""
        from pricing_engine import load_discounts_from_db
        discounts = load_discounts_from_db("/app/supermarket.db")
        d3 = next(d for d in discounts if d["id"] == "D3")
        assert d3["type"] == "bundle"
        assert abs(d3["percent_off"] - 25) < 0.01
        assert set(d3["products"]) == {
            "TOOTH_BRUSH", "TOOTH_PASTE", "MOUTH_WASH"
        }


class TestBasicCases:
    def test_empty_cart(self):
        assert calculate_optimal_total({}, CATALOG, DISCOUNTS) == 0.00

    def test_no_applicable_discounts(self):
        """Apple juice has no discount rule; full price applies."""
        cart = {"APPLE_JUICE": 2}
        assert calculate_optimal_total(cart, CATALOG, DISCOUNTS) == 5.98


class TestSingleDiscountType:
    def test_buy_n_get_m_free_exact(self):
        """3 soaps: buy 2 get 1 free -> pay 2 * 1.49 = 2.98."""
        cart = {"SOAP": 3}
        assert calculate_optimal_total(cart, CATALOG, DISCOUNTS) == 2.98

    def test_multi_buy_exact(self):
        """4 milks: 2 groups of 2-for-$2 -> $4.00."""
        cart = {"MILK": 4}
        assert calculate_optimal_total(cart, CATALOG, DISCOUNTS) == 4.00

    def test_percentage_discount(self):
        """3 rice at 10% off: 3 * 2.49 * 0.9 = 6.723 -> 6.72."""
        cart = {"RICE": 3}
        assert calculate_optimal_total(cart, CATALOG, DISCOUNTS) == 6.72

    def test_buy_n_get_m_free_remainder(self):
        """7 soaps: 2 complete groups (pay 4) + 1 remainder -> 5 * 1.49 = 7.45."""
        cart = {"SOAP": 7}
        assert calculate_optimal_total(cart, CATALOG, DISCOUNTS) == 7.45


class TestCompetingDiscounts:
    def test_bundle_beats_greedy_multi_buy(self):
        """
        Greedy: D1 (3 TB for $5) + D2 (20% TP) + MW full -> $13.78.
        Optimal: D3 bundle (25% off TB+TP+MW=$8.60) + 2 TB full -> $12.58.
        """
        cart = {"TOOTH_BRUSH": 3, "TOOTH_PASTE": 1, "MOUTH_WASH": 1}
        assert calculate_optimal_total(cart, CATALOG, DISCOUNTS) == 12.58

    def test_cheapest_free_beats_multi_buy(self):
        """
        Greedy: D1 (3 TB for $5) + 2 full -> $8.98.
        Optimal: D7 (3 TB, cheapest free = $3.98) + 2 full -> $7.96.
        """
        cart = {"TOOTH_BRUSH": 5}
        assert calculate_optimal_total(cart, CATALOG, DISCOUNTS) == 7.96

    def test_homogeneous_grouping_optimal(self):
        """
        Greedy: D1 (3 TB=$5) + D7 (3 MW, cheapest=$11.98) -> $16.98.
        Optimal: D7 (3 MW=$11.98) + D7 (3 TB=$3.98) -> $15.96.
        """
        cart = {"TOOTH_BRUSH": 3, "MOUTH_WASH": 3}
        assert calculate_optimal_total(cart, CATALOG, DISCOUNTS) == 15.96


class TestComplexCarts:
    def test_large_mixed_cart(self):
        """
        8 product types. Greedy gets $44.79; optimal is $41.97.
        """
        cart = {
            "TOOTH_BRUSH": 4, "TOOTH_PASTE": 2, "MOUTH_WASH": 1,
            "DENTAL_FLOSS": 2, "SHAMPOO": 2, "CONDITIONER": 2,
            "SOAP": 6, "MILK": 4,
        }
        assert calculate_optimal_total(cart, CATALOG, DISCOUNTS) == 41.97

    def test_many_oral_care_items(self):
        """
        12 oral items with homogeneous grouping.
        Greedy gets $30.36; optimal is $26.92.
        """
        cart = {"TOOTH_BRUSH": 6, "TOOTH_PASTE": 3, "MOUTH_WASH": 3}
        assert calculate_optimal_total(cart, CATALOG, DISCOUNTS) == 26.92
