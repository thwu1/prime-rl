"""
Marketplace System (Refactored Facade)
=======================================
Preserves the original LegacyMarketplace public API while delegating
to decomposed internal modules.

"""

from inventory import InventoryEngine
from pricing import PricingEngine
from persistence import save_state as _save, load_state as _load


class LegacyMarketplace:
    """Marketplace engine: inventory aging, cart pricing, receipts."""

    def __init__(self):
        self._catalog = {}
        self._offers = []
        self._items = []
        self._receipt = None
        self._day = 0
        self._engine = InventoryEngine()

    def load_catalog(self, catalog):
        self._catalog = {k: float(v) for k, v in catalog.items()}

    def set_items(self, items):
        self._items = list(items)

    def set_offers(self, offers):
        self._offers = [(o[0], o[1], o[2]) for o in offers]

    def register_category_handler(self, category_name, handler_fn):
        self._engine.register_handler(category_name, handler_fn)

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def update_quality(self):
        for item in self._items:
            self._engine.update_item(item)
        self._day += 1

    # ------------------------------------------------------------------
    # Cart & receipts
    # ------------------------------------------------------------------

    def process_cart(self, cart):
        pe = PricingEngine(self._catalog)
        self._receipt = pe.process(cart, self._offers)
        return self._receipt

    def format_receipt_text(self, receipt=None):
        r = receipt if receipt is not None else self._receipt
        if r is None:
            return ""
        out = ["=" * 45, "          MARKETPLACE RECEIPT", "=" * 45]
        self._fmt_lines(out, r["lines"])
        self._fmt_discounts(out, r["discount_lines"])
        self._fmt_totals(out, r)
        return "\n".join(out)

    def _fmt_lines(self, out, lines):
        for ln in lines:
            pn = ln["product"]
            if len(pn) > 20:
                pn = pn[:17] + "..."
            out.append("{:<20s} {:>3d} x {:>7.2f} = {:>9.2f}".format(
                pn, ln["quantity"], ln["unit_price"], ln["line_total"]))

    def _fmt_discounts(self, out, disc_lines):
        if not disc_lines:
            return
        out.append("-" * 45)
        for dl in disc_lines:
            desc = dl["description"]
            if len(desc) > 34:
                desc = desc[:31] + "..."
            out.append("{:<34s} {:>9.2f}".format(desc, dl["amount"]))

    def _fmt_totals(self, out, r):
        out.append("-" * 45)
        out.append("{:<34s} {:>9.2f}".format("Subtotal:", r["subtotal"]))
        if r["discount_total"] > 0:
            out.append("{:<34s} {:>9.2f}".format(
                "Discounts:", -r["discount_total"]))
        out.append("=" * 45)
        out.append("{:<34s} {:>9.2f}".format("TOTAL:", r["total"]))
        out.append("=" * 45)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_inventory_report(self):
        out = ["name, sell_in, quality"]
        for itm in self._items:
            out.append("{}, {}, {}".format(itm.name, itm.sell_in, itm.quality))
        return "\n".join(out)

    def run_simulation(self, days, daily_cart=None):
        results = []
        for d in range(days):
            report = {"day": d}
            report["inventory_before"] = self._snapshot()
            self.update_quality()
            report["inventory_after"] = self._snapshot()
            if daily_cart is not None:
                receipt = self.process_cart(daily_cart)
                report["receipt_text"] = self.format_receipt_text(receipt)
            results.append(report)
        return results

    def _snapshot(self):
        return [
            "{}, {}, {}".format(it.name, it.sell_in, it.quality)
            for it in self._items
        ]

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def save_state(self):
        return _save(self._day, self._catalog, self._items, self._offers)

    def load_state(self, json_str):
        day, catalog, items, offers = _load(json_str)
        self._day = day
        self._catalog = catalog
        self._items = items
        self._offers = offers
        self._receipt = None
