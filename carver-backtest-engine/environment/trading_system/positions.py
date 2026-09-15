"""Position sizing module."""
import numpy as np


def compute_positions(combined_forecast, vol, pointsize, fx,
                      capital, vol_target_pct, avg_abs_forecast,
                      instrument_weight, idm):
    annual_vol = vol * 252
    instrument_value_vol = annual_vol * pointsize * fx
    vol_scalar = (capital * vol_target_pct / 100.0) / \
                 (instrument_value_vol * avg_abs_forecast)
    subsystem_pos = combined_forecast * vol_scalar
    portfolio_pos = subsystem_pos * instrument_weight * idm
    return subsystem_pos, portfolio_pos
