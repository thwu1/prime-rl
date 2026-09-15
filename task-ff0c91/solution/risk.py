
"""Portfolio Value-at-Risk: historical and parametric (Delta-Normal).

Computes VaR at 95%/99% confidence, 10-day Basel scaling,
CVaR / Expected Shortfall, and component VaR decomposition.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Position:
    """A portfolio position."""
    symbol: str
    quantity: float
    current_price: float

    def notional(self) -> float:
        return self.quantity * self.current_price

    def _is_valid(self) -> bool:
        return (bool(self.symbol.strip())
                and math.isfinite(self.quantity)
                and math.isfinite(self.current_price)
                and self.current_price > 0.0)


@dataclass
class VarResult:
    """Result of a VaR calculation."""
    var_95_1d_usd: float
    var_99_1d_usd: float
    var_99_10d_usd: float
    var_95_1d_pct: float
    var_99_1d_pct: float
    cvar_95_usd: float
    portfolio_notional: float
    component_var: Dict[str, float] = field(default_factory=dict)


class VarCalculator:
    """Portfolio VaR calculator with historical and parametric methods."""

    def __init__(self, min_history_days: int):
        self._returns: Dict[str, List[float]] = {}
        self._min_history = min_history_days

    def update_returns(self, symbol: str, daily_return_pct: float) -> None:
        """Feed a daily return (in percent)."""
        if not symbol.strip() or not math.isfinite(daily_return_pct):
            return
        hist = self._returns.setdefault(symbol, [])
        hist.append(daily_return_pct)
        if len(hist) > 252:
            hist.pop(0)

    def historical_var(self, positions: List[Position]) -> Optional[VarResult]:
        """Non-parametric VaR using actual return distribution."""
        if not positions or any(not p._is_valid() for p in positions):
            return None

        for pos in positions:
            hist = self._returns.get(pos.symbol)
            if hist is None or len(hist) < self._min_history:
                return None

        n_days = min(len(self._returns[p.symbol]) for p in positions)
        if n_days < self._min_history:
            return None

        # Portfolio P&L for each historical day
        pnl = []
        for day in range(n_days):
            day_pnl = 0.0
            for pos in positions:
                hist = self._returns[pos.symbol]
                day_pnl += pos.notional() * hist[day] / 100.0
            pnl.append(day_pnl)

        pnl_clean = [v for v in pnl if math.isfinite(v)]
        if not pnl_clean:
            return None
        pnl_clean.sort()

        n = len(pnl_clean)
        idx_95 = int((1.0 - 0.95) * n)
        idx_99 = int((1.0 - 0.99) * n)

        var_95 = -min(pnl_clean[idx_95], 0.0)
        var_99 = -min(pnl_clean[idx_99], 0.0)

        # CVaR: average of tail losses beyond VaR threshold
        tail = pnl_clean[:idx_95 + 1]
        cvar_95 = -sum(tail) / len(tail) if tail else var_95

        portfolio_notional = sum(abs(p.notional()) for p in positions)

        # Component VaR (weight-proportional)
        component_var = {}
        for pos in positions:
            w = abs(pos.notional()) / max(portfolio_notional, 1.0)
            component_var[pos.symbol] = var_99 * w

        return VarResult(
            var_95_1d_usd=var_95,
            var_99_1d_usd=var_99,
            var_99_10d_usd=var_99 * math.sqrt(10.0),
            var_95_1d_pct=var_95 / max(portfolio_notional, 1.0) * 100.0,
            var_99_1d_pct=var_99 / max(portfolio_notional, 1.0) * 100.0,
            cvar_95_usd=cvar_95,
            portfolio_notional=portfolio_notional,
            component_var=component_var,
        )

    def parametric_var(self, positions: List[Position]) -> Optional[VarResult]:
        """Delta-Normal VaR assuming Gaussian returns and zero correlation."""
        if not positions or any(not p._is_valid() for p in positions):
            return None

        portfolio_variance = 0.0
        component_var = {}

        for pos in positions:
            hist = self._returns.get(pos.symbol)
            if hist is None or len(hist) < self._min_history:
                return None

            daily_vol = self._std_dev(hist)
            pos_dollar_vol = abs(pos.notional()) * daily_vol / 100.0

            portfolio_variance += pos_dollar_vol ** 2
            component_var[pos.symbol] = pos_dollar_vol * 2.326

        portfolio_vol = math.sqrt(portfolio_variance)
        var_95 = portfolio_vol * 1.645
        var_99 = portfolio_vol * 2.326
        portfolio_notional = sum(abs(p.notional()) for p in positions)

        return VarResult(
            var_95_1d_usd=var_95,
            var_99_1d_usd=var_99,
            var_99_10d_usd=var_99 * math.sqrt(10.0),
            var_95_1d_pct=var_95 / max(portfolio_notional, 1.0) * 100.0,
            var_99_1d_pct=var_99 / max(portfolio_notional, 1.0) * 100.0,
            cvar_95_usd=var_95 * 1.2,  # approximate CVaR for normal
            portfolio_notional=portfolio_notional,
            component_var=component_var,
        )

    @staticmethod
    def _std_dev(returns: List[float]) -> float:
        clean = [r for r in returns if math.isfinite(r)]
        if len(clean) < 2:
            return 0.0
        n = len(clean)
        mean = sum(clean) / n
        variance = sum((r - mean) ** 2 for r in clean) / (n - 1)
        return math.sqrt(variance)
