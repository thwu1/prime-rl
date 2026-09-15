"""
Marketplace System (Refactored)
===============================
Conforms to specification.md. All functions have cyclomatic complexity <= 5.

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
        self._custom_handlers = {}
        self._category_handlers = {
            "Normal": self._update_normal,
            "Aged": self._update_aged,
            "Legendary": self._update_legendary,
            "Backstage Pass": self._update_backstage,
            "Perishable": self._update_perishable,
            "Conjured": self._update_conjured,
        }
        self._offer_dispatch = {
            "PercentOff": self._apply_percent_off,
            "BuyNGetFree": self._apply_buy_n_get_free,
            "FlatDiscount": self._apply_flat_discount,
            "Bundle": self._apply_bundle,
        }

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def load_catalog(self, catalog):
        self._catalog = {k: float(v) for k, v in catalog.items()}

    def set_items(self, items):
        self._items = list(items)

    def set_offers(self, offers):
        self._offers = [(o[0], o[1], o[2]) for o in offers]

    def register_category_handler(self, category_name, handler_fn):
        """Register a custom handler for an item category.

        The handler receives an Item and is responsible for updating
        quality, sell_in, and enforcing bounds for one day.  Custom
        handlers take priority over built-in category logic.
        """
        self._custom_handlers[category_name] = handler_fn

    # ------------------------------------------------------------------
    # Inventory updates
    # ------------------------------------------------------------------

    def update_quality(self):
        self._quality_changes = []
        for item in self._items:
            prev_q = item.quality
            handler = self._custom_handlers.get(item.category)
            if handler:
                handler(item)
            else:
                self._dispatch_update(item)
            self._quality_changes.append(item.quality - prev_q)
        self._day += 1

    def _dispatch_update(self, item):
        handler = self._category_handlers.get(item.category)
        if handler:
            handler(item)

    def _update_normal(self, item):
        rate = 2 if item.sell_in <= 0 else 1
        item.quality = max(item.quality - rate, self.QUALITY_MIN)
        item.sell_in -= 1

    def _update_aged(self, item):
        rate = 2 if item.sell_in <= 0 else 1
        item.quality = min(item.quality + rate, self.QUALITY_MAX)
        item.sell_in -= 1

    def _update_legendary(self, item):
        pass

    def _update_backstage(self, item):
        if item.sell_in <= 0:
            item.quality = 0
        elif item.sell_in <= 5:
            item.quality = min(item.quality + 3, self.QUALITY_MAX)
        elif item.sell_in <= 10:
            item.quality = min(item.quality + 2, self.QUALITY_MAX)
        else:
            item.quality = min(item.quality + 1, self.QUALITY_MAX)
        item.sell_in -= 1

    def _update_perishable(self, item):
        rate = 4 if item.sell_in <= 0 else 2
        item.quality = max(item.quality - rate, self.PERISHABLE_MIN)
        item.sell_in -= 1

    def _update_conjured(self, item):
        rate = 4 if item.sell_in <= 0 else 2
        item.quality = max(item.quality - rate, self.QUALITY_MIN)
        item.sell_in -= 1

    # ------------------------------------------------------------------
    # Cart processing
    # ------------------------------------------------------------------

    def process_cart(self, cart):
        self._last_cart = cart
        lines, subtotal = self._build_cart_lines(cart)
        self._subtotal_cache = subtotal
        disc_tot, disc_lines = self._apply_all_offers(cart, subtotal)
        total = round(subtotal - disc_tot, 2)
        self._receipt = {
            "lines": lines,
            "discount_lines": disc_lines,
            "subtotal": round(subtotal, 2),
            "discount_total": round(disc_tot, 2),
            "total": total,
        }
        return self._receipt

    def _build_cart_lines(self, cart):
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
        return lines, subtotal

    def _apply_all_offers(self, cart, subtotal):
        disc_tot = 0.0
        disc_lines = []
        for otype, oprod, oarg in self._offers:
            handler = self._offer_dispatch.get(otype)
            if handler:
                disc_tot, disc_lines = handler(
                    cart, oprod, oarg, subtotal, disc_tot, disc_lines,
                )
        return disc_tot, disc_lines

    def _apply_percent_off(self, cart, product, pct, subtotal,
                           disc_tot, disc_lines):
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

    def _apply_buy_n_get_free(self, cart, product, n, subtotal,
                              disc_tot, disc_lines):
        n = int(n)
        for pn, qty in cart:
            if pn == product:
                up = self._catalog.get(product, 0.0)
                free = qty // (n + 1)
                d = round(free * up, 2)
                disc_tot += d
                disc_lines.append({
                    "description": "Buy {} get 1 free: {}".format(n, product),
                    "amount": round(-d, 2),
                })
        return disc_tot, disc_lines

    def _apply_flat_discount(self, cart, oprod, threshold, subtotal,
                             disc_tot, disc_lines):
        threshold = float(threshold)
        if subtotal >= threshold:
            d = round(threshold * 0.1, 2)
            disc_tot += d
            disc_lines.append({
                "description": "Flat ${:.2f} off (spend >= ${:.2f})".format(
                    d, threshold),
                "amount": round(-d, 2),
            })
        return disc_tot, disc_lines

    def _apply_bundle(self, cart, oprod, bundle_products, subtotal,
                      disc_tot, disc_lines):
        cart_set = set()
        for pn, _ in cart:
            cart_set.add(pn)
        if not set(bundle_products).issubset(cart_set):
            return disc_tot, disc_lines
        bt = self._bundle_line_total(cart, bundle_products)
        d = round(bt * 0.10, 2)
        disc_tot += d
        disc_lines.append({
            "description": "Bundle discount (10%)",
            "amount": round(-d, 2),
        })
        return disc_tot, disc_lines

    def _bundle_line_total(self, cart, bundle_products):
        bp_set = set(bundle_products)
        total = 0.0
        for pn, qty in cart:
            if pn in bp_set:
                total += self._catalog.get(pn, 0.0) * qty
        return total

    # ------------------------------------------------------------------
    # Receipt formatting
    # ------------------------------------------------------------------

    def format_receipt_text(self, receipt=None):
        r = receipt if receipt is not None else self._receipt
        if r is None:
            return ""
        out = ["=" * 45, "          MARKETPLACE RECEIPT", "=" * 45]
        self._format_line_items(out, r["lines"])
        self._format_discount_lines(out, r["discount_lines"])
        self._format_totals(out, r)
        return "\n".join(out)

    def _format_line_items(self, out, lines):
        for ln in lines:
            pn = ln["product"]
            if len(pn) > 20:
                pn = pn[:17] + "..."
            out.append("{:<20s} {:>3d} x {:>7.2f} = {:>9.2f}".format(
                pn, ln["quantity"], ln["unit_price"], ln["line_total"]))

    def _format_discount_lines(self, out, disc_lines):
        if not disc_lines:
            return
        out.append("-" * 45)
        for dl in disc_lines:
            desc = dl["description"]
            if len(desc) > 34:
                desc = desc[:31] + "..."
            out.append("{:<34s} {:>9.2f}".format(desc, dl["amount"]))

    def _format_totals(self, out, r):
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
            report["inventory_before"] = self._snapshot_inventory()
            self.update_quality()
            report["inventory_after"] = self._snapshot_inventory()
            if daily_cart is not None:
                receipt = self.process_cart(daily_cart)
                report["receipt_text"] = self.format_receipt_text(receipt)
            results.append(report)
        return results

    def _snapshot_inventory(self):
        return [
            "{}, {}, {}".format(it.name, it.sell_in, it.quality)
            for it in self._items
        ]
