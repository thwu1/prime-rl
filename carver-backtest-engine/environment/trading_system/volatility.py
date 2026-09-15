"""Volatility estimation module."""
import numpy as np


def compute_mixed_vol(price_changes, days, slow_vol_years,
                      proportion_of_slow_vol, vol_abs_min):
    fast_vol = price_changes.ewm(span=days, min_periods=days).std()
    slow_days = int(slow_vol_years * 252)
    slow_vol = price_changes.rolling(slow_days, min_periods=days).std()
    vol = fast_vol * proportion_of_slow_vol + slow_vol * (1.0 - proportion_of_slow_vol)
    vol = vol.clip(lower=vol_abs_min)
    return vol
