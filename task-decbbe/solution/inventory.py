"""Inventory update engine with category handler dispatch.

"""

QUALITY_MAX = 50
QUALITY_MIN = 0
PERISHABLE_MIN = -10


class InventoryEngine:
    """Manages item quality updates with pluggable category handlers."""

    def __init__(self):
        self._custom_handlers = {}
        self._builtin = {
            "Normal": self._update_normal,
            "Aged": self._update_aged,
            "Legendary": self._update_legendary,
            "Backstage Pass": self._update_backstage,
            "Perishable": self._update_perishable,
            "Conjured": self._update_conjured,
        }

    def register_handler(self, category, handler_fn):
        self._custom_handlers[category] = handler_fn

    def update_item(self, item):
        custom = self._custom_handlers.get(item.category)
        if custom:
            custom(item)
            return
        builtin = self._builtin.get(item.category)
        if builtin:
            builtin(item)

    def _update_normal(self, item):
        rate = 2 if item.sell_in <= 0 else 1
        item.quality = max(item.quality - rate, QUALITY_MIN)
        item.sell_in -= 1

    def _update_aged(self, item):
        rate = 2 if item.sell_in <= 0 else 1
        item.quality = min(item.quality + rate, QUALITY_MAX)
        item.sell_in -= 1

    def _update_legendary(self, item):
        pass

    def _update_backstage(self, item):
        if item.sell_in <= 0:
            item.quality = 0
        elif item.sell_in <= 5:
            item.quality = min(item.quality + 3, QUALITY_MAX)
        elif item.sell_in <= 10:
            item.quality = min(item.quality + 2, QUALITY_MAX)
        else:
            item.quality = min(item.quality + 1, QUALITY_MAX)
        item.sell_in -= 1

    def _update_perishable(self, item):
        rate = 4 if item.sell_in <= 0 else 2
        item.quality = max(item.quality - rate, PERISHABLE_MIN)
        item.sell_in -= 1

    def _update_conjured(self, item):
        rate = 4 if item.sell_in <= 0 else 2
        item.quality = max(item.quality - rate, QUALITY_MIN)
        item.sell_in -= 1
