"""Cart pricing engine with discount pipeline and 50% cap.

"""

DISCOUNT_CAP_RATIO = 0.5


class PricingEngine:
    """Computes cart totals with configurable discount types."""

    def __init__(self, catalog):
        self._catalog = catalog
        self._dispatch = {
            "PercentOff": self._percent_off,
            "BuyNGetFree": self._buy_n_get_free,
            "FlatDiscount": self._flat_discount,
            "Bundle": self._bundle,
        }

    def process(self, cart, offers):
        lines, subtotal = self._build_lines(cart)
        dt, dl = self._compute_discounts(cart, offers, subtotal)
        dt = min(dt, round(subtotal * DISCOUNT_CAP_RATIO, 2))
        total = round(subtotal - dt, 2)
        return {
            "lines": lines,
            "discount_lines": dl,
            "subtotal": round(subtotal, 2),
            "discount_total": round(dt, 2),
            "total": total,
        }

    def _build_lines(self, cart):
        lines = []
        subtotal = 0.0
        for pn, qty in cart:
            up = self._catalog.get(pn, 0.0)
            lt = round(up * qty, 2)
            subtotal += lt
            lines.append({
                "product": pn, "quantity": qty,
                "unit_price": up, "line_total": lt,
            })
        return lines, subtotal

    def _compute_discounts(self, cart, offers, subtotal):
        dt = 0.0
        dl = []
        for otype, oprod, oarg in offers:
            handler = self._dispatch.get(otype)
            if handler:
                dt, dl = handler(cart, oprod, oarg, subtotal, dt, dl)
        return dt, dl

    def _percent_off(self, cart, product, pct, subtotal, dt, dl):
        for pn, qty in cart:
            if pn == product:
                up = self._catalog.get(product, 0.0)
                d = round(up * qty * pct / 100.0, 2)
                dt += d
                dl.append({
                    "description": "{:.0f}% off {}".format(pct, product),
                    "amount": round(-d, 2),
                })
        return dt, dl

    def _buy_n_get_free(self, cart, product, n, subtotal, dt, dl):
        n = int(n)
        for pn, qty in cart:
            if pn == product:
                up = self._catalog.get(product, 0.0)
                free = qty // (n + 1)
                d = round(free * up, 2)
                dt += d
                dl.append({
                    "description": "Buy {} get 1 free: {}".format(n, product),
                    "amount": round(-d, 2),
                })
        return dt, dl

    def _flat_discount(self, cart, oprod, threshold, subtotal, dt, dl):
        threshold = float(threshold)
        if subtotal >= threshold:
            d = round(threshold * 0.1, 2)
            dt += d
            dl.append({
                "description": "Flat ${:.2f} off (spend >= ${:.2f})".format(
                    d, threshold),
                "amount": round(-d, 2),
            })
        return dt, dl

    def _bundle(self, cart, oprod, products, subtotal, dt, dl):
        cart_set = {pn for pn, _ in cart}
        if not set(products).issubset(cart_set):
            return dt, dl
        bp = set(products)
        bt = sum(
            self._catalog.get(pn, 0.0) * qty
            for pn, qty in cart if pn in bp
        )
        d = round(bt * 0.10, 2)
        dt += d
        dl.append({
            "description": "Bundle discount (10%)",
            "amount": round(-d, 2),
        })
        return dt, dl
