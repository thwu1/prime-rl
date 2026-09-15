"""Volatility regime classifier using fast/slow EMA ratio of absolute returns."""

CRISIS_THRESH = 2.5
HIGH_VOL_THRESH = 1.4
LOW_VOL_THRESH = 0.7

REGIME_PARAMS = {
    'LowVol': {'gamma': 0.05, 'spread_mult': 0.6, 'size_mult': 1.2, 'urgency_mult': 0.8},
    'Normal': {'gamma': 0.10, 'spread_mult': 1.0, 'size_mult': 1.0, 'urgency_mult': 1.0},
    'HighVol': {'gamma': 0.20, 'spread_mult': 2.0, 'size_mult': 0.6, 'urgency_mult': 1.3},
    'Crisis': {'gamma': 0.40, 'spread_mult': 4.0, 'size_mult': 0.2, 'urgency_mult': 0.3},
}


class RegimeDetector:
    def __init__(self, fast_alpha=0.15, slow_alpha=0.03, min_regime_ticks=5):
        self.fast_alpha = fast_alpha
        self.slow_alpha = slow_alpha
        self.min_regime_ticks = min_regime_ticks
        self.vol_fast_ema = 1.0
        self.vol_slow_ema = 1.0
        self._regime = 'Normal'
        self.ticks_in_regime = 0
        self._vol_ratio = 1.0

    def update(self, vol_observation):
        self.vol_fast_ema = (self.fast_alpha * vol_observation
                             + (1 - self.fast_alpha) * self.vol_fast_ema)
        self.vol_slow_ema = (self.slow_alpha * vol_observation
                             + (1 - self.slow_alpha) * self.vol_slow_ema)

        self._vol_ratio = self.vol_fast_ema / max(self.vol_slow_ema, 1e-10)

        if self._vol_ratio > CRISIS_THRESH:
            proposed = 'LowVol'
        elif self._vol_ratio > HIGH_VOL_THRESH:
            proposed = 'HighVol'
        elif self._vol_ratio < LOW_VOL_THRESH:
            proposed = 'Crisis'
        else:
            proposed = 'Normal'

        self.ticks_in_regime += 1
        if proposed != self._regime and self.ticks_in_regime >= self.min_regime_ticks:
            self._regime = proposed
            self.ticks_in_regime = 0

        return self._regime

    def regime(self):
        return self._regime

    def vol_ratio(self):
        return self._vol_ratio

    def params(self):
        return dict(REGIME_PARAMS.get(self._regime, REGIME_PARAMS['Normal']))

    def get_regime_params_map(self):
        return dict(REGIME_PARAMS)
