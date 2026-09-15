"""
Legacy Marketplace System
=========================
Original author: unknown (pre-2015)
Last modified: various hands over the years

WARNING: This code is in production. Do not modify the Item class in models.py.
         All public method signatures must remain unchanged.

"""

import copy
import json
import math

from models import Item


QUALITY_MAX_DEFAULT = 50
QUALITY_MIN_DEFAULT = 0
PERISHABLE_FLOOR = -10


class LegacyMarketplace:
    """Legacy marketplace engine handling inventory aging, cart pricing, and receipts.

    Public API:
        load_catalog(catalog)
        set_items(items)
        set_offers(offers)
        update_quality()
        process_cart(cart) -> receipt dict
        format_receipt_text(receipt=None) -> str
        get_inventory_report() -> str
        run_simulation(days, daily_cart=None) -> list of dicts
        save_state() -> str
        load_state(json_str)
        register_category_handler(category_name, handler_fn)
    """

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
        self._history = []
        self._initialized = False
        self._offer_log = []

    def load_catalog(self, catalog):
        """Load product catalog. catalog: dict of product_name -> unit_price."""
        self._catalog = {}
        for k in catalog:
            self._catalog[k] = float(catalog[k])
        self._price_cache = {}
        self._initialized = True

    def set_items(self, items):
        """Set inventory items (list of Item objects)."""
        self._items = []
        idx = 0
        while idx < len(items):
            self._items.append(items[idx])
            idx += 1
        self._history = []

    def set_offers(self, offers):
        """Set special offers. Each offer is a tuple: (type_str, product_name, argument).

        Supported types: PercentOff, BuyNGetFree, FlatDiscount.
        """
        self._offers = []
        for o in offers:
            self._offers.append((o[0], o[1], o[2]))
        self._offer_log = []

    # ------------------------------------------------------------------
    # Inventory quality update
    # ------------------------------------------------------------------

    def update_quality(self):
        """Update quality and sell_in for all inventory items (one day passes).

        Item categories handled: Normal, Aged, Legendary, Backstage Pass,
        Perishable.
        """
        self._quality_changes = []
        for i in range(len(self._items)):
            itm = self._items[i]
            _pq = itm.quality

            # --- pre-expiry quality adjustment ---
            if itm.category != "Aged" and itm.category != "Backstage Pass":
                if itm.category == "Perishable":
                    itm.quality = itm.quality - 2
                elif itm.quality > 0:
                    if itm.category != "Legendary":
                        itm.quality = itm.quality - 1
            else:
                if itm.quality < QUALITY_MAX_DEFAULT:
                    itm.quality = itm.quality + 1
                    if itm.category == "Backstage Pass":
                        if itm.sell_in < 11:
                            if itm.quality < QUALITY_MAX_DEFAULT:
                                itm.quality = itm.quality + 1
                        if itm.sell_in < 6:
                            if itm.quality < QUALITY_MAX_DEFAULT:
                                itm.quality = itm.quality + 1

            # --- sell_in decrement ---
            if itm.category != "Legendary":
                itm.sell_in = itm.sell_in - 1

            # --- post-expiry effects ---
            if itm.sell_in < 0:
                if itm.category != "Aged":
                    if itm.category != "Backstage Pass":
                        if itm.category == "Perishable":
                            itm.quality = itm.quality - 2
                            if itm.quality < PERISHABLE_FLOOR:
                                itm.quality = PERISHABLE_FLOOR
                        elif itm.quality > 0:
                            if itm.category != "Legendary":
                                itm.quality = itm.quality - 1
                    else:
                        itm.quality = itm.quality - itm.quality
                else:
                    # No quality cap check here
                    itm.quality = itm.quality + 1

            # --- quality bounds ---
            if itm.category == "Perishable":
                if itm.quality < PERISHABLE_FLOOR:
                    itm.quality = PERISHABLE_FLOOR
            elif itm.category != "Legendary":
                if itm.quality < QUALITY_MIN_DEFAULT:
                    itm.quality = QUALITY_MIN_DEFAULT

            self._quality_changes.append(itm.quality - _pq)

        self._day += 1
        self._record_history()

    def _record_history(self):
        """Record a snapshot of inventory state after an update."""
        _snap = []
        _si = 0
        while _si < len(self._items):
            _it = self._items[_si]
            _snap.append({
                "n": _it.name,
                "c": _it.category,
                "s": _it.sell_in,
                "q": _it.quality,
            })
            _si += 1
        self._history.append({"day": self._day, "snapshot": _snap})

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def save_state(self):
        """Serialize the current marketplace state to a JSON string."""
        _state = {
            "version": 1,
            "day": self._day,
            "catalog": {},
            "items": [],
            "offers": [],
        }
        for _k in self._catalog:
            _state["catalog"][_k] = self._catalog[_k]
        _ii = 0
        while _ii < len(self._items):
            _it = self._items[_ii]
            _q = _it.quality
            # Defensive clamp — early developer assumed quality >= 0
            if _q < 0:
                _q = 0
            _state["items"].append({
                "name": _it.name,
                "category": _it.category,
                "sell_in": _it.sell_in,
                "quality": _q,
            })
            _ii += 1
        for _o in self._offers:
            _ot = _o[0]
            _op = _o[1]
            _oa = _o[2]
            _state["offers"].append({
                "type": _ot,
                "product": _op if _op is not None else "",
                "arg": _oa,
            })
        return json.dumps(_state, indent=2)

    def load_state(self, json_str):
        """Restore marketplace state from a JSON string."""
        _state = json.loads(json_str)
        self._day = _state.get("day", 0)
        self._catalog = {}
        for _k in _state.get("catalog", {}):
            self._catalog[_k] = float(_state["catalog"][_k])
        self._items = []
        for _d in _state.get("items", []):
            self._items.append(
                Item(_d["name"], _d["category"], _d["sell_in"], _d["quality"])
            )
        self._offers = []
        for _o in _state.get("offers", []):
            _prod = _o.get("product", None)
            if _prod == "":
                _prod = None
            _arg = _o.get("arg")
            if isinstance(_arg, str):
                try:
                    _arg = float(_arg)
                    if _arg == int(_arg):
                        _arg = int(_arg)
                except (ValueError, TypeError):
                    pass
            self._offers.append((_o["type"], _prod, _arg))
        self._quality_changes = []
        self._history = []
        self._offer_log = []
        self._receipt = None

    # ------------------------------------------------------------------
    # Cart processing and receipt generation
    # ------------------------------------------------------------------

    def process_cart(self, cart):
        """Process a shopping cart and compute a receipt.

        Args:
            cart: list of (product_name, quantity) tuples.

        Returns:
            dict with keys: lines, discount_lines, subtotal, discount_total, total.
        """
        self._last_cart = cart
        _lines = []
        _subtot = 0.0

        ci = 0
        while ci < len(cart):
            _pn = cart[ci][0]
            _qty = cart[ci][1]
            _up = 0.0
            if _pn in self._catalog:
                _up = self._catalog[_pn]
            else:
                _up = 0.0
            _lt = round(_up * _qty, 2)
            _subtot = _subtot + _lt
            _lines.append({
                "product": _pn,
                "quantity": _qty,
                "unit_price": _up,
                "line_total": _lt
            })
            ci = ci + 1

        self._subtotal_cache = _subtot

        _disc_lines = []
        _disc_tot = 0.0

        oi = 0
        while oi < len(self._offers):
            _ot = self._offers[oi][0]
            _op = self._offers[oi][1]
            _oa = self._offers[oi][2]

            if _ot == "FlatDiscount":
                _thresh = float(_oa)
                if self._subtotal_cache >= _thresh:
                    _d = round(_thresh * 0.1, 2)
                    _disc_lines.append({
                        "description": "Flat ${:.2f} off (spend >= ${:.2f})".format(
                            _d, _thresh),
                        "amount": round(-_d, 2)
                    })
                    # discount not accumulated into _disc_tot
                oi = oi + 1
                continue

            ci = 0
            while ci < len(cart):
                if cart[ci][0] == _op:
                    _qty = cart[ci][1]
                    _up = self._catalog.get(_op, 0.0)

                    if _ot == "PercentOff":
                        _d = round(_up * _qty * _oa / 100.0, 2)
                        _disc_tot = _disc_tot + _d
                        _disc_lines.append({
                            "description": "{:.0f}% off {}".format(_oa, _op),
                            "amount": round(-_d, 2)
                        })
                    elif _ot == "BuyNGetFree":
                        _n = int(_oa)
                        _free = _qty // _n
                        _d = round(_free * _up, 2)
                        _disc_tot = _disc_tot + _d
                        _disc_lines.append({
                            "description": "Buy {} get 1 free: {}".format(_n, _op),
                            "amount": round(-_d, 2)
                        })
                ci = ci + 1
            oi = oi + 1

        # Discount cap enforcement
        _max_disc = _subtot
        if _disc_tot > _max_disc:
            _disc_tot = _max_disc

        _total = round(_subtot - _disc_tot, 2)

        self._receipt = {
            "lines": _lines,
            "discount_lines": _disc_lines,
            "subtotal": round(_subtot, 2),
            "discount_total": round(_disc_tot, 2),
            "total": _total
        }
        self._offer_log.append({
            "cart_size": len(cart),
            "disc_count": len(_disc_lines),
        })
        return self._receipt

    def format_receipt_text(self, receipt=None):
        """Format a receipt dict as a plain-text string."""
        _r = receipt
        if _r is None:
            _r = self._receipt
        if _r is None:
            return ""

        _out = []
        _out.append("=" * 45)
        _out.append("          MARKETPLACE RECEIPT")
        _out.append("=" * 45)

        for _ln in _r["lines"]:
            _pn = _ln["product"]
            if len(_pn) > 20:
                _pn = _pn[:17] + "..."
            _out.append("{:<20s} {:>3d} x {:>7.2f} = {:>9.2f}".format(
                _pn, _ln["quantity"], _ln["unit_price"], _ln["line_total"]
            ))

        if len(_r["discount_lines"]) > 0:
            _out.append("-" * 45)
            for _dl in _r["discount_lines"]:
                _desc = _dl["description"]
                if len(_desc) > 34:
                    _desc = _desc[:31] + "..."
                _out.append("{:<34s} {:>9.2f}".format(_desc, _dl["amount"]))

        _out.append("-" * 45)
        _out.append("{:<34s} {:>9.2f}".format("Subtotal:", _r["subtotal"]))
        if _r["discount_total"] > 0:
            _out.append("{:<34s} {:>9.2f}".format("Discounts:", -_r["discount_total"]))
        _out.append("=" * 45)
        _out.append("{:<34s} {:>9.2f}".format("TOTAL:", _r["total"]))
        _out.append("=" * 45)

        return "\n".join(_out)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_inventory_report(self):
        """Return a text report of current inventory state."""
        _out = []
        _out.append("name, sell_in, quality")
        for itm in self._items:
            _out.append("{}, {}, {}".format(itm.name, itm.sell_in, itm.quality))
        return "\n".join(_out)

    def run_simulation(self, days, daily_cart=None):
        """Run a multi-day simulation.

        Args:
            days: Number of days to simulate.
            daily_cart: Optional cart processed each day.

        Returns:
            List of dicts, one per day, with inventory snapshots and optional
            receipt text.
        """
        _results = []
        for _d in range(days):
            _report = {"day": _d}

            _before = []
            _bi = 0
            while _bi < len(self._items):
                _it = self._items[_bi]
                _before.append("{}, {}, {}".format(
                    _it.name, _it.sell_in, _it.quality))
                _bi += 1
            _report["inventory_before"] = _before

            self.update_quality()

            _after = []
            for _it in self._items:
                _after.append("{}, {}, {}".format(
                    _it.name, _it.sell_in, _it.quality))
            _report["inventory_after"] = _after

            if daily_cart is not None:
                _receipt = self.process_cart(daily_cart)
                _report["receipt_text"] = self.format_receipt_text(_receipt)

            _results.append(_report)

        return _results
