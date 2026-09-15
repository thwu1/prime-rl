"""Data models for the marketplace system.

DO NOT MODIFY THIS FILE - the Item class interface is used by external systems.
"""


class Item:
    """Represents an inventory item.

    Attributes:
        name: Display name of the item.
        category: One of Normal, Aged, Legendary, Backstage Pass, Perishable,
                  or Conjured.
        sell_in: Days remaining to sell the item.
        quality: Current quality value of the item.
    """

    def __init__(self, name, category, sell_in, quality):
        self.name = name
        self.category = category
        self.sell_in = sell_in
        self.quality = quality

    def __repr__(self):
        return "%s (%s), %s, %s" % (self.name, self.category, self.sell_in, self.quality)
