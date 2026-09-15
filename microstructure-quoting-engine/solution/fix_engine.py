#!/usr/bin/env python3
"""
Fix all 6 bugs in the market-making engine modules.

Bug 1 (garch.py): alpha and beta coefficients are swapped in the variance
    update equation. The GARCH(1,1) update is sigma^2_t = omega + alpha*r^2 +
    beta*sigma^2_{t-1}, but the code applies beta to the squared return and
    alpha to the lagged variance.

Bug 2 (microstructure.py - microprice): The size-weighting is inverted. The
    microprice should weight the ask price by the bid queue depth and vice
    versa (deeper bid queue implies buying pressure, pulling price toward ask).
    The code weights each price by its OWN side's depth.

Bug 3 (microstructure.py - OFI): The order flow imbalance tick is computed as
    delta_ask - delta_bid instead of delta_bid - delta_ask, inverting the sign
    of buying vs selling pressure.

Bug 4 (regime.py): The Crisis and LowVol labels are swapped in the
    classification logic. When vol_ratio exceeds the crisis threshold, the code
    assigns 'LowVol', and when vol_ratio is below the low-vol threshold, it
    assigns 'Crisis'.

Bug 5 (quoting.py): The reservation price adjustment for inventory has the
    wrong sign. It should subtract q*gamma*sigma^2*tau from fair value (to push
    price down when long, encouraging sells), but the code adds it.

Bug 6 (toxicity.py): The adverse selection check is inverted. It flags fills
    where post_move > threshold (favorable moves) as toxic, instead of
    flagging fills where post_move < -threshold (adverse moves).
"""

import os


def fix_file(path, replacements):
    with open(path, 'r') as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise ValueError(f"Pattern not found in {path}: {old!r}")
        content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)


# Bug 1: GARCH variance update has alpha/beta swapped
fix_file('/app/engine/garch.py', [
    (
        'new_var = p.omega + p.beta * return_t ** 2 + p.alpha * self.conditional_variance',
        'new_var = p.omega + p.alpha * return_t ** 2 + p.beta * self.conditional_variance',
    ),
])

# Bug 2: microprice size weighting is inverted
fix_file('/app/engine/microstructure.py', [
    (
        'return bid * (bid_size / total) + ask * (ask_size / total)',
        'return ask * (bid_size / total) + bid * (ask_size / total)',
    ),
])

# Bug 3: OFI sign is inverted (delta_ask - delta_bid should be delta_bid - delta_ask)
fix_file('/app/engine/microstructure.py', [
    (
        'ofi_tick = delta_ask - delta_bid',
        'ofi_tick = delta_bid - delta_ask',
    ),
])

# Bug 4: Regime labels Crisis/LowVol are swapped
fix_file('/app/engine/regime.py', [
    (
        "proposed = 'LowVol'\n        elif self._vol_ratio > HIGH_VOL_THRESH:\n            proposed = 'HighVol'\n        elif self._vol_ratio < LOW_VOL_THRESH:\n            proposed = 'Crisis'",
        "proposed = 'Crisis'\n        elif self._vol_ratio > HIGH_VOL_THRESH:\n            proposed = 'HighVol'\n        elif self._vol_ratio < LOW_VOL_THRESH:\n            proposed = 'LowVol'",
    ),
])

# Bug 5: Reservation price sign is wrong (+ should be -)
fix_file('/app/engine/quoting.py', [
    (
        'reservation = fair_value + q * gamma * sigma_sq * tau_safe',
        'reservation = fair_value - q * gamma * sigma_sq * tau_safe',
    ),
])

# Bug 6: Toxicity adverse move detection is inverted
fix_file('/app/engine/toxicity.py', [
    (
        'is_toxic = post_move > self.adverse_move_threshold',
        'is_toxic = post_move < -self.adverse_move_threshold',
    ),
])

print("All 6 bugs fixed successfully.")
