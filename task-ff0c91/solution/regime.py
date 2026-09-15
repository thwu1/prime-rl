
"""Volatility regime classifier using fast/slow EMA ratio.

Four regimes (LowVol, Normal, HighVol, Crisis), each mapped to concrete
trading parameter adjustments. Based on RegimeFolio (2025).

Classification thresholds (vol_ratio = fast_ema / slow_ema):
  Crisis:  ratio > 2.5
  HighVol: ratio > 1.4
  LowVol:  ratio < 0.7
  Normal:  otherwise
"""

from dataclasses import dataclass
from enum import Enum


@dataclass
class RegimeParams:
    """Regime-conditioned trading parameters."""
    gamma: float          # risk aversion for A-S quoting
    spread_mult: float    # spread multiplier
    size_mult: float      # position size multiplier
    urgency_mult: float   # urgency for taking
    mr_threshold: float   # z-score threshold for mean reversion
    max_inventory_mult: float  # inventory limit multiplier


# Thresholds
_CRISIS_THRESH = 2.5
_HIGH_VOL_THRESH = 1.4
_LOW_VOL_THRESH = 0.7

# Regime parameter table (calibrated from RegimeFolio 2025)
_REGIME_PARAMS = {
    'LOW_VOL': RegimeParams(
        gamma=0.05, spread_mult=0.6, size_mult=1.2,
        urgency_mult=0.8, mr_threshold=1.2, max_inventory_mult=1.5,
    ),
    'NORMAL': RegimeParams(
        gamma=0.10, spread_mult=1.0, size_mult=1.0,
        urgency_mult=1.0, mr_threshold=0.8, max_inventory_mult=1.0,
    ),
    'HIGH_VOL': RegimeParams(
        gamma=0.20, spread_mult=2.0, size_mult=0.6,
        urgency_mult=1.3, mr_threshold=0.6, max_inventory_mult=0.7,
    ),
    'CRISIS': RegimeParams(
        gamma=0.40, spread_mult=4.0, size_mult=0.2,
        urgency_mult=0.3, mr_threshold=2.0, max_inventory_mult=0.3,
    ),
}


class Regime(Enum):
    LOW_VOL = "low_vol"
    NORMAL = "normal"
    HIGH_VOL = "high_vol"
    CRISIS = "crisis"

    def params(self) -> RegimeParams:
        return _REGIME_PARAMS[self.name]


class RegimeDetector:
    """Two-state volatility regime classifier using fast/slow EMA ratio.

    Fast EMA (~7-tick half-life) captures regime transitions.
    Slow EMA (~23-tick half-life) represents the baseline.
    """

    def __init__(self, fast_alpha: float = 0.15, slow_alpha: float = 0.03,
                 min_regime_ticks: int = 5):
        self._vol_fast_ema = 1.0
        self._vol_slow_ema = 1.0
        self._fast_alpha = fast_alpha
        self._slow_alpha = slow_alpha
        self._current_regime = Regime.NORMAL
        self._ticks_in_regime = 0
        self._min_regime_ticks = min_regime_ticks
        self._vol_ratio = 1.0

    def update(self, vol_observation: float) -> 'Regime':
        """Update with new volatility observation and return current regime."""
        self._vol_fast_ema = (self._fast_alpha * vol_observation
                              + (1.0 - self._fast_alpha) * self._vol_fast_ema)
        self._vol_slow_ema = (self._slow_alpha * vol_observation
                              + (1.0 - self._slow_alpha) * self._vol_slow_ema)

        self._vol_ratio = self._vol_fast_ema / max(self._vol_slow_ema, 1e-10)

        # Classify
        if self._vol_ratio > _CRISIS_THRESH:
            proposed = Regime.CRISIS
        elif self._vol_ratio > _HIGH_VOL_THRESH:
            proposed = Regime.HIGH_VOL
        elif self._vol_ratio < _LOW_VOL_THRESH:
            proposed = Regime.LOW_VOL
        else:
            proposed = Regime.NORMAL

        # Debounce
        self._ticks_in_regime += 1
        if proposed != self._current_regime and self._ticks_in_regime >= self._min_regime_ticks:
            if proposed == Regime.CRISIS or self._ticks_in_regime >= self._min_regime_ticks:
                self._current_regime = proposed
                self._ticks_in_regime = 0

        return self._current_regime

    @property
    def regime(self) -> Regime:
        return self._current_regime

    @property
    def vol_ratio(self) -> float:
        return self._vol_ratio
