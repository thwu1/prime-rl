"""Tests for marketplace system conformance, architecture, and extensibility.

"""

import ast
import hashlib
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, "/app")

from models import Item
from legacy_system import LegacyMarketplace


# ======================================================================
# Helpers
# ======================================================================

def make_mp(items=None, offers=None, catalog=None):
    mp = LegacyMarketplace()
    if catalog:
        mp.load_catalog(catalog)
    if items:
        mp.set_items(items)
    if offers:
        mp.set_offers(offers)
    return mp


def update_single(category, sell_in, quality):
    item = Item("test_item", category, sell_in, quality)
    mp = make_mp(items=[item])
    mp.update_quality()
    return item.sell_in, item.quality


# ======================================================================
# models.py integrity
# ======================================================================

MODELS_SHA256 = "3f7dce9d6f770051e6fd280e2a1d1b670439269e64d81b22c2848da0e410a140"


class TestModelsIntegrity:
    def test_models_unchanged(self):
        with open("/app/models.py", "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        assert digest == MODELS_SHA256, (
            f"models.py has been modified (expected {MODELS_SHA256}, got {digest})"
        )


# ======================================================================
# Code quality: cyclomatic complexity across ALL modules
# ======================================================================

class TestCodeQuality:
    def test_cyclomatic_complexity_within_threshold(self):
        """Every function/method in ALL app modules must have CC <= 5."""
        import glob as glob_mod
        violations = []
        py_files = glob_mod.glob("/app/*.py")
        excluded = {"__init__.py", "run_scenario.py"}
        for fpath in py_files:
            fname = os.path.basename(fpath)
            if fname in excluded:
                continue
            result = subprocess.run(
                ["radon", "cc", "-s", "-j", fpath],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                violations.append("radon failed on {}: {}".format(fname, result.stderr))
                continue
            data = json.loads(result.stdout)
            for filepath, blocks in data.items():
                for block in blocks:
                    if block["complexity"] > 5:
                        violations.append(
                            "{} {}.{}: CC={}".format(
                                fname, block["type"], block["name"],
                                block["complexity"],
                            )
                        )
                    if "methods" in block:
                        for method in block["methods"]:
                            if method["complexity"] > 5:
                                violations.append(
                                    "{} {}.{}: CC={}".format(
                                        fname, block["name"],
                                        method["name"],
                                        method["complexity"],
                                    )
                                )
        assert not violations, (
            "Functions exceeding cyclomatic complexity 5:\n"
            + "\n".join("  - " + v for v in violations)
        )

    def test_module_decomposition(self):
        """System must be decomposed into >= 3 modules beyond models.py."""
        import glob as glob_mod
        py_files = glob_mod.glob("/app/*.py")
        excluded = {"models.py", "__init__.py", "run_scenario.py"}
        app_modules = [
            os.path.basename(f) for f in py_files
            if os.path.basename(f) not in excluded
        ]
        assert len(app_modules) >= 3, (
            "Expected >= 3 application modules, found {}: {}".format(
                len(app_modules), ", ".join(sorted(app_modules))
            )
        )


# ======================================================================
# Architecture: no circular imports
# ======================================================================

class TestArchitecture:
    def test_no_circular_imports(self):
        """No circular import dependencies between application modules."""
        import glob as glob_mod

        py_files = glob_mod.glob("/app/*.py")
        excluded = {"__init__.py", "run_scenario.py"}

        modules = set()
        for fpath in py_files:
            fname = os.path.basename(fpath)
            if fname not in excluded:
                modules.add(fname[:-3])

        graph = {m: set() for m in modules}
        for fpath in py_files:
            fname = os.path.basename(fpath)
            if fname in excluded:
                continue
            modname = fname[:-3]
            with open(fpath) as f:
                try:
                    tree = ast.parse(f.read())
                except SyntaxError:
                    continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        dep = alias.name.split(".")[0]
                        if dep in modules and dep != modname:
                            graph[modname].add(dep)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    dep = node.module.split(".")[0]
                    if dep in modules and dep != modname:
                        graph[modname].add(dep)

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {m: WHITE for m in modules}

        def dfs(u):
            color[u] = GRAY
            for v in graph.get(u, set()):
                if color[v] == GRAY:
                    return "{} -> {}".format(u, v)
                if color[v] == WHITE:
                    result = dfs(v)
                    if result:
                        return result
            color[u] = BLACK
            return None

        for m in sorted(modules):
            if color[m] == WHITE:
                cycle = dfs(m)
                assert cycle is None, "Circular import detected: {}".format(cycle)


# ======================================================================
# Extensibility: register_category_handler
# ======================================================================

class TestExtensibility:
    def test_register_custom_handler(self):
        """A custom handler for a new category must be called."""
        mp = LegacyMarketplace()
        calls = []

        def handler(item):
            calls.append(item.name)
            item.quality += 10
            item.sell_in -= 1

        mp.register_category_handler("CustomTest", handler)
        item = Item("Widget", "CustomTest", 5, 20)
        mp.set_items([item])
        mp.update_quality()
        assert calls == ["Widget"], "Handler not called; calls={}".format(calls)
        assert item.quality == 30
        assert item.sell_in == 4

    def test_custom_handler_overrides_builtin(self):
        """A custom handler for an existing category must override built-in."""
        mp = LegacyMarketplace()

        def handler(item):
            item.quality = 99
            item.sell_in -= 1

        mp.register_category_handler("Normal", handler)
        item = Item("Overridden", "Normal", 5, 20)
        mp.set_items([item])
        mp.update_quality()
        assert item.quality == 99
        assert item.sell_in == 4

    def test_unregistered_categories_use_builtin(self):
        """Registering a handler for one category must not affect others."""
        mp = LegacyMarketplace()

        def handler(item):
            item.quality = 99
            item.sell_in -= 1

        mp.register_category_handler("CustomOnly", handler)
        item = Item("Normal Item", "Normal", 5, 20)
        mp.set_items([item])
        mp.update_quality()
        assert item.quality == 19


# ======================================================================
# Normal items
# ======================================================================

class TestNormalItems:
    def test_degrades_by_one(self):
        s, q = update_single("Normal", 10, 20)
        assert s == 9
        assert q == 19

    def test_double_degrade_expired(self):
        s, q = update_single("Normal", 0, 10)
        assert s == -1
        assert q == 8

    def test_quality_floor_zero(self):
        _, q = update_single("Normal", 5, 0)
        assert q == 0

    def test_quality_floor_expired(self):
        _, q = update_single("Normal", -1, 1)
        assert q == 0

    def test_quality_never_negative(self):
        _, q = update_single("Normal", 0, 1)
        assert q >= 0


# ======================================================================
# Aged items
# ======================================================================

class TestAgedItems:
    def test_increases_by_one(self):
        s, q = update_single("Aged", 5, 10)
        assert s == 4
        assert q == 11

    def test_double_increase_expired(self):
        s, q = update_single("Aged", 0, 10)
        assert s == -1
        assert q == 12

    def test_quality_capped_at_50_when_expired(self):
        _, q = update_single("Aged", 0, 49)
        assert q <= 50, "Aged quality exceeded 50: got {}".format(q)

    def test_quality_stays_at_50_when_already_max(self):
        _, q = update_single("Aged", -1, 50)
        assert q <= 50, "Aged quality exceeded 50: got {}".format(q)

    def test_quality_converges_to_50(self):
        item = Item("Aged Brie", "Aged", 2, 0)
        mp = make_mp(items=[item])
        for _ in range(60):
            mp.update_quality()
        assert item.quality == 50


# ======================================================================
# Legendary items
# ======================================================================

class TestLegendaryItems:
    def test_never_changes(self):
        s, q = update_single("Legendary", 0, 80)
        assert s == 0
        assert q == 80

    def test_never_changes_negative_sell_in(self):
        s, q = update_single("Legendary", -5, 80)
        assert s == -5
        assert q == 80


# ======================================================================
# Backstage Pass items
# ======================================================================

class TestBackstagePassItems:
    def test_increase_by_one_above_ten(self):
        _, q = update_single("Backstage Pass", 15, 20)
        assert q == 21

    def test_increase_by_two_at_ten(self):
        _, q = update_single("Backstage Pass", 10, 20)
        assert q == 22

    def test_increase_by_two_at_six(self):
        _, q = update_single("Backstage Pass", 6, 20)
        assert q == 22

    def test_increase_by_three_at_five(self):
        _, q = update_single("Backstage Pass", 5, 20)
        assert q == 23

    def test_increase_by_three_at_one(self):
        _, q = update_single("Backstage Pass", 1, 20)
        assert q == 23

    def test_drops_to_zero_at_sell_in_zero(self):
        _, q = update_single("Backstage Pass", 0, 20)
        assert q == 0

    def test_stays_zero_after_concert(self):
        _, q = update_single("Backstage Pass", -1, 0)
        assert q == 0

    def test_quality_cap(self):
        _, q = update_single("Backstage Pass", 5, 49)
        assert q <= 50


# ======================================================================
# Perishable items
# ======================================================================

class TestPerishableItems:
    def test_degrades_by_two(self):
        s, q = update_single("Perishable", 5, 20)
        assert s == 4
        assert q == 18

    def test_degrades_by_four_expired(self):
        s, q = update_single("Perishable", 0, 10)
        assert s == -1
        assert q == 6

    def test_quality_floor_at_neg_ten(self):
        _, q = update_single("Perishable", -1, -8)
        assert q == -10

    def test_quality_stays_at_floor(self):
        _, q = update_single("Perishable", -1, -10)
        assert q == -10

    def test_can_go_negative(self):
        _, q = update_single("Perishable", 5, 1)
        assert q == -1


# ======================================================================
# Conjured items
# ======================================================================

class TestConjuredItems:
    def test_degrades_by_two(self):
        s, q = update_single("Conjured", 5, 20)
        assert s == 4
        assert q == 18

    def test_degrades_by_four_expired(self):
        s, q = update_single("Conjured", 0, 20)
        assert s == -1
        assert q == 16

    def test_quality_floor_zero(self):
        _, q = update_single("Conjured", 5, 1)
        assert q == 0

    def test_quality_floor_expired(self):
        _, q = update_single("Conjured", 0, 3)
        assert q == 0

    def test_quality_never_negative(self):
        _, q = update_single("Conjured", -1, 0)
        assert q >= 0

    def test_multi_day_sequence(self):
        """Verify Conjured behavior over multiple days crossing expiry."""
        item = Item("Conjured Cake", "Conjured", 3, 20)
        mp = make_mp(items=[item])
        expected = [18, 16, 14, 10, 6, 2, 0, 0]
        for i, eq in enumerate(expected):
            mp.update_quality()
            assert item.quality == eq, (
                "Day {}: expected quality {}, got {}".format(i + 1, eq, item.quality)
            )


# ======================================================================
# PercentOff discount
# ======================================================================

class TestPercentOff:
    def test_applies_correctly(self):
        mp = make_mp(
            catalog={"Brie": 15.00},
            offers=[("PercentOff", "Brie", 10)],
        )
        receipt = mp.process_cart([("Brie", 2)])
        assert receipt["discount_total"] == pytest.approx(3.00, abs=0.01)
        assert receipt["total"] == pytest.approx(27.00, abs=0.01)


# ======================================================================
# BuyNGetFree discount
# ======================================================================

class TestBuyNGetFree:
    def test_qty4_gives_1_free(self):
        mp = make_mp(
            catalog={"Toothbrush": 3.00},
            offers=[("BuyNGetFree", "Toothbrush", 2)],
        )
        receipt = mp.process_cart([("Toothbrush", 4)])
        assert receipt["discount_total"] == pytest.approx(3.00, abs=0.01)
        assert receipt["total"] == pytest.approx(9.00, abs=0.01)

    def test_qty6_gives_2_free(self):
        mp = make_mp(
            catalog={"Toothbrush": 3.00},
            offers=[("BuyNGetFree", "Toothbrush", 2)],
        )
        receipt = mp.process_cart([("Toothbrush", 6)])
        assert receipt["discount_total"] == pytest.approx(6.00, abs=0.01)

    def test_qty3_gives_1_free(self):
        mp = make_mp(
            catalog={"Toothbrush": 3.00},
            offers=[("BuyNGetFree", "Toothbrush", 2)],
        )
        receipt = mp.process_cart([("Toothbrush", 3)])
        assert receipt["discount_total"] == pytest.approx(3.00, abs=0.01)

    def test_qty2_gives_0_free(self):
        mp = make_mp(
            catalog={"Toothbrush": 3.00},
            offers=[("BuyNGetFree", "Toothbrush", 2)],
        )
        receipt = mp.process_cart([("Toothbrush", 2)])
        assert receipt["discount_total"] == pytest.approx(0.00, abs=0.01)

    def test_qty7_gives_2_free(self):
        mp = make_mp(
            catalog={"Toothbrush": 3.00},
            offers=[("BuyNGetFree", "Toothbrush", 2)],
        )
        receipt = mp.process_cart([("Toothbrush", 7)])
        assert receipt["discount_total"] == pytest.approx(6.00, abs=0.01)


# ======================================================================
# FlatDiscount
# ======================================================================

class TestFlatDiscount:
    def test_reduces_total(self):
        mp = make_mp(
            catalog={"Milk": 3.50, "Bread": 10.00, "Cheese": 8.00},
            offers=[("FlatDiscount", None, 20.0)],
        )
        receipt = mp.process_cart([("Milk", 1), ("Bread", 1), ("Cheese", 1)])
        subtotal = 3.50 + 10.00 + 8.00
        expected_disc = round(20.0 * 0.1, 2)
        assert receipt["discount_total"] == pytest.approx(expected_disc, abs=0.01)
        assert receipt["total"] == pytest.approx(subtotal - expected_disc, abs=0.01)

    def test_not_applied_below_threshold(self):
        mp = make_mp(
            catalog={"Milk": 3.50},
            offers=[("FlatDiscount", None, 20.0)],
        )
        receipt = mp.process_cart([("Milk", 1)])
        assert receipt["discount_total"] == pytest.approx(0.00, abs=0.01)
        assert receipt["total"] == pytest.approx(3.50, abs=0.01)


# ======================================================================
# Bundle discount
# ======================================================================

class TestBundleDiscount:
    def test_all_present(self):
        mp = make_mp(
            catalog={"Toothbrush": 1.00, "Toothpaste": 2.00, "Milk": 3.50},
            offers=[("Bundle", None, ["Toothbrush", "Toothpaste"])],
        )
        receipt = mp.process_cart([
            ("Toothbrush", 2), ("Toothpaste", 1), ("Milk", 1),
        ])
        assert receipt["discount_total"] == pytest.approx(0.40, abs=0.01)
        assert receipt["total"] == pytest.approx(7.10, abs=0.01)

    def test_missing_product(self):
        mp = make_mp(
            catalog={"Toothbrush": 1.00, "Toothpaste": 2.00},
            offers=[("Bundle", None, ["Toothbrush", "Toothpaste"])],
        )
        receipt = mp.process_cart([("Toothbrush", 2)])
        assert receipt["discount_total"] == pytest.approx(0.00, abs=0.01)

    def test_description(self):
        mp = make_mp(
            catalog={"A": 5.00, "B": 3.00},
            offers=[("Bundle", None, ["A", "B"])],
        )
        receipt = mp.process_cart([("A", 1), ("B", 1)])
        descriptions = [dl["description"] for dl in receipt["discount_lines"]]
        assert any("Bundle" in d and "10%" in d for d in descriptions)

    def test_coexists_with_other_offers(self):
        mp = make_mp(
            catalog={"A": 10.00, "B": 5.00, "C": 2.00},
            offers=[
                ("PercentOff", "C", 50),
                ("Bundle", None, ["A", "B"]),
            ],
        )
        receipt = mp.process_cart([("A", 1), ("B", 1), ("C", 1)])
        assert receipt["discount_total"] == pytest.approx(2.50, abs=0.01)


# ======================================================================
# Discount cap at 50% of subtotal
# ======================================================================

class TestDiscountCap:
    def test_cap_at_50_percent(self):
        """A single discount exceeding 50% must be capped."""
        mp = make_mp(
            catalog={"Widget": 10.00},
            offers=[("PercentOff", "Widget", 60)],
        )
        receipt = mp.process_cart([("Widget", 1)])
        # Raw: 60% of $10 = $6.00, cap at 50% = $5.00
        assert receipt["discount_total"] == pytest.approx(5.00, abs=0.01)
        assert receipt["total"] == pytest.approx(5.00, abs=0.01)

    def test_no_cap_when_below(self):
        """Discounts below 50% are not capped."""
        mp = make_mp(
            catalog={"Widget": 10.00},
            offers=[("PercentOff", "Widget", 30)],
        )
        receipt = mp.process_cart([("Widget", 1)])
        assert receipt["discount_total"] == pytest.approx(3.00, abs=0.01)
        assert receipt["total"] == pytest.approx(7.00, abs=0.01)

    def test_cap_with_combined_discounts(self):
        """Combined discounts exceeding 50% must be capped (tests bug interaction)."""
        mp = make_mp(
            catalog={"A": 10.00},
            offers=[
                ("PercentOff", "A", 45),
                ("FlatDiscount", None, 8.0),
            ],
        )
        receipt = mp.process_cart([("A", 1)])
        # PercentOff: 45% of $10 = $4.50
        # FlatDiscount: subtotal($10) >= $8 threshold -> 10% of $8 = $0.80
        # Raw total: $5.30 = 53% of $10 -> cap at 50% = $5.00
        assert receipt["discount_total"] == pytest.approx(5.00, abs=0.01)
        assert receipt["total"] == pytest.approx(5.00, abs=0.01)


# ======================================================================
# State persistence
# ======================================================================

class TestStatePersistence:
    def test_round_trip_basic(self):
        """Basic state must round-trip through save/load."""
        mp1 = make_mp(
            catalog={"Milk": 3.50},
            items=[Item("Milk Jug", "Normal", 5, 20)],
        )
        mp1.update_quality()
        state = mp1.save_state()

        mp2 = LegacyMarketplace()
        mp2.load_state(state)

        report = mp2.get_inventory_report()
        assert "Milk Jug, 4, 19" in report

    def test_preserves_negative_quality(self):
        """Perishable items with negative quality must survive round-trip."""
        mp1 = LegacyMarketplace()
        item = Item("Fish", "Perishable", -1, -5)
        mp1.set_items([item])
        state = mp1.save_state()

        mp2 = LegacyMarketplace()
        mp2.load_state(state)

        report = mp2.get_inventory_report()
        assert "Fish, -1, -5" in report, (
            "Negative quality lost in round-trip: {}".format(report)
        )

    def test_round_trip_bundle_offer(self):
        """Bundle offers with list arguments must round-trip correctly."""
        mp1 = LegacyMarketplace()
        mp1.load_catalog({"A": 5.00, "B": 3.00})
        mp1.set_offers([("Bundle", None, ["A", "B"])])
        state = mp1.save_state()

        mp2 = LegacyMarketplace()
        mp2.load_state(state)

        receipt = mp2.process_cart([("A", 1), ("B", 1)])
        # Bundle: 10% of (5+3) = 0.80
        assert receipt["discount_total"] == pytest.approx(0.80, abs=0.01)

    def test_preserves_day(self):
        """Day counter must be preserved across save/load."""
        mp1 = LegacyMarketplace()
        mp1.set_items([Item("X", "Normal", 10, 20)])
        for _ in range(5):
            mp1.update_quality()
        state = mp1.save_state()

        state_dict = json.loads(state)
        assert state_dict["day"] == 5


# ======================================================================
# Receipt formatting
# ======================================================================

class TestReceiptFormat:
    def test_format_returns_string(self):
        mp = make_mp(catalog={"Milk": 3.50})
        receipt = mp.process_cart([("Milk", 1)])
        text = mp.format_receipt_text(receipt)
        assert isinstance(text, str)
        assert "MARKETPLACE RECEIPT" in text
        assert "TOTAL" in text

    def test_contains_product_line(self):
        mp = make_mp(catalog={"Milk": 3.50})
        receipt = mp.process_cart([("Milk", 2)])
        text = mp.format_receipt_text(receipt)
        assert "Milk" in text
        assert "7.00" in text


# ======================================================================
# Public API preserved
# ======================================================================

class TestPublicAPI:
    def test_has_required_methods(self):
        mp = LegacyMarketplace()
        required = [
            "load_catalog", "set_items", "set_offers", "update_quality",
            "process_cart", "format_receipt_text", "get_inventory_report",
            "run_simulation", "register_category_handler",
            "save_state", "load_state",
        ]
        for name in required:
            assert callable(getattr(mp, name, None)), "Missing method: {}".format(name)

    def test_run_simulation_returns_list(self):
        mp = make_mp(items=[Item("Vest", "Normal", 5, 10)])
        results = mp.run_simulation(3)
        assert isinstance(results, list)
        assert len(results) == 3
        assert "day" in results[0]
