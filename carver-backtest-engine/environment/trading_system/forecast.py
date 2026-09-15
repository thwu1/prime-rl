"""Forecast scaling, combination, and diversification multiplier."""
import pandas as pd
import numpy as np


def scale_and_cap_forecasts(raw_forecasts, rules_config, cap):
    scaled = {}
    for rule, raw in raw_forecasts.items():
        scalar = rules_config[rule]['forecast_scalar']
        scaled[rule] = (raw * scalar).clip(-cap, cap)
    return scaled


def compute_fdm(scaled_df, weights):
    """Compute forecast diversification multiplier.

    Currently returns a fixed value. This needs to be properly
    estimated from the correlation structure of the forecasts.
    """
    return 1.0


def combine_forecasts(scaled_forecasts, weights, fdm, cap, index):
    total_w = sum(weights.values())
    combined = pd.Series(0.0, index=index)
    for rule, w in weights.items():
        if rule in scaled_forecasts:
            combined = combined.add(
                scaled_forecasts[rule] * (w / total_w), fill_value=0.0)
    combined = (combined * fdm).clip(-cap, cap)
    return combined
