# Marketplace System Specification

## Overview

The marketplace system manages an inventory of items whose quality changes
daily, a cart/receipt subsystem for pricing with discounts, and a state
persistence layer for saving and restoring system state.

## Item Categories and Quality Rules

Each day, every non-Legendary item has its quality adjusted and its `sell_in`
value decremented by 1. An item is considered expired when `sell_in <= 0` at
the start of the day's update. Quality adjustments apply the full daily rate
in a single step (incorporating expiry status).

### Normal

- Rate: -1/day; -2/day when expired.
- Quality bounds: [0, 50].

### Aged

- Rate: +1/day; +2/day when expired.
- Quality bounds: [0, 50].

### Legendary

- Quality and `sell_in` never change. Quality is always 80.

### Backstage Pass

- More than 10 days remaining: +1/day.
- 6-10 days remaining (inclusive): +2/day.
- 1-5 days remaining (inclusive): +3/day.
- When expired (sell_in <= 0): quality drops to 0.
- Quality max: 50.

### Perishable

- Rate: -2/day; -4/day when expired.
- Quality bounds: [-10, 50].

### Conjured

- Rate: -2/day; -4/day when expired.
- Quality bounds: [0, 50].

## Discount Types

### PercentOff

- Format: `("PercentOff", "product_name", percentage)`
- Applies `percentage`% discount to all units of the named product in the cart.

### BuyNGetFree

- Format: `("BuyNGetFree", "product_name", N)`
- Buy N, get 1 free: for every complete group of (N + 1) items, 1 is free.
- Free count: `quantity // (N + 1)`.
- Discount amount: `free_count * unit_price`.

### FlatDiscount

- Format: `("FlatDiscount", None, threshold)`
- When the cart subtotal >= threshold, discount is `threshold * 0.1`.
- This discount must be included in the discount total and subtracted from
  the cart total.

### Bundle

- Format: `("Bundle", None, ["product1", "product2", ...])`
- When all listed products are present in the cart, apply 10% off their
  combined line totals (across all quantities).
- If any bundle product is missing from the cart, no discount is applied.
- Discount description on receipt: `"Bundle discount (10%)"`.

## Discount Cap

The total discount applied to a cart must never exceed 50% of the cart
subtotal. If the raw sum of all individual discounts exceeds
`subtotal * 0.5`, the `discount_total` is capped at `subtotal * 0.5`.

## State Persistence

### save_state() -> str

Returns a JSON string representing the complete marketplace state:
- `version`: format version (integer)
- `day`: current simulation day counter
- `catalog`: product name to unit price mapping
- `items`: list of item dicts with `name`, `category`, `sell_in`, `quality`
- `offers`: list of offer dicts with `type`, `product`, `arg`

Quality values must be preserved exactly as-is, including negative values
for Perishable items. Offer arguments that are lists (e.g., Bundle product
lists) must serialize correctly as JSON arrays. Products that are `None`
(e.g., for FlatDiscount and Bundle) must serialize as JSON `null`.

### load_state(json_str)

Restores marketplace state from a JSON string produced by `save_state()`.
Must correctly reconstruct all item data (including negative quality) and
all offer data (including list arguments and null products).

## Receipt Structure

`process_cart(cart)` returns a dict with keys:

- `lines`: list of `{"product", "quantity", "unit_price", "line_total"}` dicts.
- `discount_lines`: list of `{"description", "amount"}` dicts (amount is negative).
- `subtotal`: sum of line totals (before discounts).
- `discount_total`: sum of all discount amounts (positive number, after cap).
- `total`: `subtotal - discount_total`.

`format_receipt_text(receipt)` returns a formatted plain-text string with
header "MARKETPLACE RECEIPT", product lines, discount lines, subtotal,
discount summary, and total.

## Extensibility Requirement

The `LegacyMarketplace` class must provide a
`register_category_handler(category_name, handler_fn)` method. When
`update_quality()` processes an item whose category matches a registered
handler, it must call `handler_fn(item)` instead of built-in logic. The
handler is responsible for all updates to the item (quality adjustment,
sell_in decrement, bounds enforcement). Custom handlers take priority over
built-in category logic.

## Architectural Requirements

The implementation must be decomposed into at least three Python modules
in the `/app/` directory (not counting `models.py`, `__init__.py`, or
`run_scenario.py`). The `legacy_system.py` file must act as a facade,
importing from internal modules and preserving all public method signatures.

No circular import dependencies are permitted between modules.

All functions and methods across all modules must have a cyclomatic
complexity score of 5 or less, as measured by `radon cc -s`.
