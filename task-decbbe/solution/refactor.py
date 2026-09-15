#!/usr/bin/env python3
"""Refactor legacy_system.py: fix 3 bugs, add Conjured + Bundle support.

"""

REFACTORED_CODE = '''\
"""
Marketplace System (Refactored)
===============================
Bugs fixed: #1 (Aged cap), #2 (BuyNGetFree), #3 (FlatDiscount).
New features: Conjured items, Bundle discounts.

"""

from models import Item


class LegacyMarketplace:
    """Marketplace engine: inventory aging, cart pricing, receipts."""

    QUALITY_MAX = 50
    QUALITY_MIN = 0
    PERISHABLE_MIN = -10

    def __init__(self):
        self._catalog = {}
        self._offers = []
        self._items = []
        self._receipt = None
        self._day = 0
        self._quality_changes = []
        self._subtotal_cache = 0.0
        self._price_cache = {}
        self._last_cart = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def load_catalog(self, catalog):
        self._catalog = {k: float(v) for k, v in catalog.items()}

    def set_items(self, items):
        self._items = list(items)

    def set_offers(self, offers):
        self._offers = [(o[0], o[1], o[2]) for o in offers]

    # ------------------------------------------------------------------
    # Inventory updates
    # ------------------------------------------------------------------

    def update_quality(self):
        self._quality_changes = []
        for item in self._items:
            prev_q = item.quality
            self._update_item(item)
            self._quality_changes.append(item.quality - prev_q)
        self._day += 1

    def _update_item(self, item):
        cat = item.category
        if cat == "Legendary":
            return

        expired = item.sell_in <= 0

        if cat == "Normal":
            rate = 2 if expired else 1
            item.quality = max(item.quality - rate, self.QUALITY_MIN)
        elif cat == "Conjured":
            rate = 4 if expired else 2
            item.quality = max(item.quality - rate, self.QUALITY_MIN)
        elif cat == "Perishable":
            rate = 4 if expired else 2
            item.quality = max(item.quality - rate, self.PERISHABLE_MIN)
        elif cat == "Aged":
            rate = 2 if expired else 1
            item.quality = min(item.quality + rate, self.QUALITY_MAX)
        elif cat == "Backstage Pass":
            if expired:
                item.quality = 0
            elif item.sell_in <= 5:
                item.quality = min(item.quality + 3, self.QUALITY_MAX)
            elif item.sell_in <= 10:
                item.quality = min(item.quality + 2, self.QUALITY_MAX)
            else:
                item.quality = min(item.quality + 1, self.QUALITY_MAX)

        item.sell_in -= 1

    # ------------------------------------------------------------------
    # Cart & receipts
    # ------------------------------------------------------------------

    def process_cart(self, cart):
        self._last_cart = cart
        lines = []
        subtotal = 0.0

        for pn, qty in cart:
            up = self._catalog.get(pn, 0.0)
            lt = round(up * qty, 2)
            subtotal += lt
            lines.append({
                "product": pn,
                "quantity": qty,
                "unit_price": up,
                "line_total": lt,
            })

        self._subtotal_cache = subtotal
        disc_lines = []
        disc_tot = 0.0

        for otype, oprod, oarg in self._offers:
            if otype == "PercentOff":
                disc_tot, disc_lines = self._apply_percent_off(
                    cart, oprod, oarg, disc_tot, disc_lines)
            elif otype == "BuyNGetFree":
                disc_tot, disc_lines = self._apply_buy_n_get_free(
                    cart, oprod, oarg, disc_tot, disc_lines)
            elif otype == "FlatDiscount":
                disc_tot, disc_lines = self._apply_flat_discount(
                    subtotal, oarg, disc_tot, disc_lines)
            elif otype == "Bundle":
                disc_tot, disc_lines = self._apply_bundle(
                    cart, oarg, disc_tot, disc_lines)

        total = round(subtotal - disc_tot, 2)

        self._receipt = {
            "lines": lines,
            "discount_lines": disc_lines,
            "subtotal": round(subtotal, 2),
            "discount_total": round(disc_tot, 2),
            "total": total,
        }
        return self._receipt

    def _apply_percent_off(self, cart, product, pct, disc_tot, disc_lines):
        for pn, qty in cart:
            if pn == product:
                up = self._catalog.get(product, 0.0)
                d = round(up * qty * pct / 100.0, 2)
                disc_tot += d
                disc_lines.append({
                    "description": "{:.0f}% off {}".format(pct, product),
                    "amount": round(-d, 2),
                })
        return disc_tot, disc_lines

    def _apply_buy_n_get_free(self, cart, product, n, disc_tot, disc_lines):
        n = int(n)
        for pn, qty in cart:
            if pn == product:
                up = self._catalog.get(product, 0.0)
                free = qty // (n + 1)  # FIX Bug #2
                d = round(free * up, 2)
                disc_tot += d
                disc_lines.append({
                    "description": "Buy {} get 1 free: {}".format(n, product),
                    "amount": round(-d, 2),
                })
        return disc_tot, disc_lines

    def _apply_flat_discount(self, subtotal, threshold, disc_tot, disc_lines):
        threshold = float(threshold)
        if subtotal >= threshold:
            d = round(threshold * 0.1, 2)
            disc_tot += d  # FIX Bug #3
            disc_lines.append({
                "description": "Flat ${:.2f} off (spend >= ${:.2f})".format(
                    d, threshold),
                "amount": round(-d, 2),
            })
        return disc_tot, disc_lines

    def _apply_bundle(self, cart, bundle_products, disc_tot, disc_lines):
        cart_products = {c[0] for c in cart}
        if not all(bp in cart_products for bp in bundle_products):
            return disc_tot, disc_lines
        bundle_total = 0.0
        for pn, qty in cart:
            if pn in bundle_products:
                up = self._catalog.get(pn, 0.0)
                bundle_total += up * qty
        d = round(bundle_total * 0.10, 2)
        disc_tot += d
        disc_lines.append({
            "description": "Bundle discount (10%)",
            "amount": round(-d, 2),
        })
        return disc_tot, disc_lines

    def format_receipt_text(self, receipt=None):
        r = receipt if receipt is not None else self._receipt
        if r is None:
            return ""

        out = []
        out.append("=" * 45)
        out.append("          MARKETPLACE RECEIPT")
        out.append("=" * 45)

        for ln in r["lines"]:
            pn = ln["product"]
            if len(pn) > 20:
                pn = pn[:17] + "..."
            out.append("{:<20s} {:>3d} x {:>7.2f} = {:>9.2f}".format(
                pn, ln["quantity"], ln["unit_price"], ln["line_total"]))

        if r["discount_lines"]:
            out.append("-" * 45)
            for dl in r["discount_lines"]:
                desc = dl["description"]
                if len(desc) > 34:
                    desc = desc[:31] + "..."
                out.append("{:<34s} {:>9.2f}".format(desc, dl["amount"]))

        out.append("-" * 45)
        out.append("{:<34s} {:>9.2f}".format("Subtotal:", r["subtotal"]))
        if r["discount_total"] > 0:
            out.append("{:<34s} {:>9.2f}".format(
                "Discounts:", -r["discount_total"]))
        out.append("=" * 45)
        out.append("{:<34s} {:>9.2f}".format("TOTAL:", r["total"]))
        out.append("=" * 45)

        return "\\n".join(out)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_inventory_report(self):
        out = ["name, sell_in, quality"]
        for itm in self._items:
            out.append("{}, {}, {}".format(itm.name, itm.sell_in, itm.quality))
        return "\\n".join(out)

    def run_simulation(self, days, daily_cart=None):
        results = []
        for d in range(days):
            report = {"day": d}
            report["inventory_before"] = [
                "{}, {}, {}".format(it.name, it.sell_in, it.quality)
                for it in self._items
            ]
            self.update_quality()
            report["inventory_after"] = [
                "{}, {}, {}".format(it.name, it.sell_in, it.quality)
                for it in self._items
            ]
            if daily_cart is not None:
                receipt = self.process_cart(daily_cart)
                report["receipt_text"] = self.format_receipt_text(receipt)
            results.append(report)
        return results
'''


def main():
    with open("/app/legacy_system.py", "w") as f:
        f.write(REFACTORED_CODE)
    print("Wrote refactored legacy_system.py")


if __name__ == "__main__":
    main()
