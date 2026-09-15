"""State persistence for the marketplace system.

"""

import json

from models import Item


def save_state(day, catalog, items, offers):
    """Serialize marketplace state to a JSON string."""
    state = {
        "version": 1,
        "day": day,
        "catalog": dict(catalog),
        "items": [
            {
                "name": it.name,
                "category": it.category,
                "sell_in": it.sell_in,
                "quality": it.quality,
            }
            for it in items
        ],
        "offers": [
            {"type": o[0], "product": o[1], "arg": o[2]}
            for o in offers
        ],
    }
    return json.dumps(state, indent=2)


def load_state(json_str):
    """Restore marketplace state from a JSON string.

    Returns:
        Tuple of (day, catalog, items, offers).
    """
    state = json.loads(json_str)
    day = state.get("day", 0)
    catalog = {k: float(v) for k, v in state.get("catalog", {}).items()}
    items = [
        Item(d["name"], d["category"], d["sell_in"], d["quality"])
        for d in state.get("items", [])
    ]
    offers = []
    for o in state.get("offers", []):
        offers.append((o["type"], o.get("product"), o.get("arg")))
    return day, catalog, items, offers
