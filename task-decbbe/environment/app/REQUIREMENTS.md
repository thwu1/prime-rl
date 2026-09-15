# Marketplace System Requirements

## Overview

The marketplace system manages an inventory of items whose quality changes
daily, and a cart/receipt subsystem that prices items and applies discounts.

## Item Categories

### Normal
- Quality degrades by 1 per day.
- Once the sell-by date has passed (sell_in becomes negative after the daily
  update), quality degrades by 2 per day instead.
- Quality is never negative (minimum 0).
- Quality is never more than 50.

### Aged
- Quality **increases** by 1 per day.
- Once the sell-by date has passed, quality increases by 2 per day instead.
- Quality is never more than 50.
- Quality is never negative.

### Legendary
- Never changes in quality or sell_in.
- Quality is always 80.

### Backstage Pass
- Quality increases by 1 when there are more than 10 days until the event.
- Quality increases by 2 when there are 6-10 days remaining (inclusive).
- Quality increases by 3 when there are 1-5 days remaining (inclusive).
- Quality drops to 0 after the event day (once sell_in becomes negative).
- Quality is never more than 50.

### Perishable
- Quality degrades by 2 per day.
- Once the sell-by date has passed, quality degrades by 4 per day instead.
- Quality minimum is **-10** (not 0 like other items).

## Daily Update Mechanics

Each day, for every non-Legendary item:

1. Quality is adjusted based on the category rules above, using the **current**
   sell_in value to determine whether the item is expired.
2. sell_in is decremented by 1.
3. If sell_in is now negative (the item just expired or was already expired),
   the additional expired-rate adjustment is applied.
4. Quality bounds are enforced (floor/ceiling per category).

## Discount Types

### PercentOff
- Format: `("PercentOff", "product_name", percentage)`
- Applies the given percentage discount to all units of the named product in
  the cart.

### BuyNGetFree
- Format: `("BuyNGetFree", "product_name", N)`
- "Buy N, get 1 free" — for every complete group of (N + 1) items purchased,
  1 item is free.
- Free item count: `quantity // (N + 1)`.
- Discount: `free_count * unit_price`.

### FlatDiscount
- Format: `("FlatDiscount", None, threshold)`
- When the cart subtotal is >= threshold, apply a flat discount of 10% of the
  threshold value.
- This discount **must** be subtracted from the cart total.

---

## Known Bugs

The following bugs exist in the current codebase and must be fixed:

### Bug #1 — Aged Item Quality Exceeds Maximum

The expired-aging path for Aged items increases quality without checking the
cap of 50. When an Aged item is expired, the post-expiry increment is applied
unconditionally, allowing quality to exceed 50.

**Reproduce:** Create an Aged item with quality 49 and sell_in 0. After one
`update_quality()` call, quality should be 50 (capped), but the buggy code
produces 51.

### Bug #2 — BuyNGetFree Gives Too Many Free Items

The BuyNGetFree discount computes `free = quantity // N` instead of
`free = quantity // (N + 1)`. This over-counts free items whenever
`quantity >= N + 2`.

**Reproduce:** Set up a BuyNGetFree offer with N=2 and a cart containing 4
units. Correct free count is `4 // 3 = 1`; buggy code gives `4 // 2 = 2`.

### Bug #3 — FlatDiscount Not Subtracted from Total

The FlatDiscount logic appends a discount line to the receipt display but does
not add the discount amount to the running discount total. The receipt shows the
discount line, but the total is not reduced.

**Reproduce:** Set up a FlatDiscount with threshold 20 and a cart with subtotal
>= 20. The receipt total should reflect the $2.00 discount, but it does not.

---

## New Features Required

### Conjured Items (New Category)

- Category name: `"Conjured"`
- Quality degrades at **twice** the normal rate: 2 per day before expiry,
  4 per day after expiry.
- Quality minimum is 0, maximum is 50.
- sell_in decrements by 1 per day, same as Normal items.

### Bundle Discount (New Offer Type)

- Offer format: `("Bundle", None, ["product1", "product2", ...])`
- When **all** products listed in the bundle are present in the cart, apply a
  10% discount to the combined total of those bundle products (across all
  quantities).
- If any bundle product is missing from the cart, no discount is applied.
- The discount description on the receipt should be `"Bundle discount (10%)"`.
