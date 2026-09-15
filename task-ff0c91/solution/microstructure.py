
"""Market microstructure signals: microprice, OFI, VPIN, Kyle's Lambda.

References:
  - Cont, Kukanov & Stoikov (2014) — OFI
  - Easley, Lopez de Prado & O'Hara (2012) — VPIN
  - Kyle (1985) — Lambda (price impact)
"""

from collections import deque


def microprice(bid: float, ask: float, bid_size: float, ask_size: float) -> float:
    """Size-weighted midpoint.

    microprice = ask * (bid_size / total) + bid * (ask_size / total)

    When bid_size >> ask_size, microprice is pulled toward ask (upward pressure).
    """
    total = bid_size + ask_size
    if total < 1e-10:
        return (bid + ask) / 2.0
    return ask * (bid_size / total) + bid * (ask_size / total)


def microprice_imbalance(bid_size: float, ask_size: float) -> float:
    """Normalized imbalance in [-1, 1]."""
    total = bid_size + ask_size
    if total < 1e-10:
        return 0.0
    return (bid_size - ask_size) / total


class OrderFlowImbalance:
    """Order Flow Imbalance (Cont et al. 2014).

    Measures net change in bid/ask volume to predict short-term price direction.
    """

    def __init__(self, window_size: int):
        self._prev_bid_price = 0.0
        self._prev_bid_size = 0.0
        self._prev_ask_price = 0.0
        self._prev_ask_size = 0.0
        self._window: deque = deque(maxlen=window_size)
        self._initialized = False

    def update(self, bid_price: float, bid_size: float,
               ask_price: float, ask_size: float) -> float:
        if not self._initialized:
            self._prev_bid_price = bid_price
            self._prev_bid_size = bid_size
            self._prev_ask_price = ask_price
            self._prev_ask_size = ask_size
            self._initialized = True
            return 0.0

        # Bid-side flow
        if bid_price > self._prev_bid_price:
            delta_bid = bid_size
        elif bid_price == self._prev_bid_price:
            delta_bid = bid_size - self._prev_bid_size
        else:
            delta_bid = -self._prev_bid_size

        # Ask-side flow
        if ask_price < self._prev_ask_price:
            delta_ask = ask_size
        elif ask_price == self._prev_ask_price:
            delta_ask = ask_size - self._prev_ask_size
        else:
            delta_ask = -self._prev_ask_size

        ofi_tick = delta_bid - delta_ask
        self._window.append(ofi_tick)

        self._prev_bid_price = bid_price
        self._prev_bid_size = bid_size
        self._prev_ask_price = ask_price
        self._prev_ask_size = ask_size

        # Normalized OFI
        s = sum(self._window)
        abs_s = sum(abs(x) for x in self._window)
        if abs_s > 0.0:
            return s / abs_s
        return 0.0


class Vpin:
    """Volume-Synchronized Probability of Informed Trading (Easley et al. 2012).

    High VPIN -> dangerous to provide liquidity (adverse selection risk).
    """

    def __init__(self, bucket_volume: float, num_buckets: int):
        self._bucket_volume = bucket_volume
        self._num_buckets = num_buckets
        self._buy_volume = 0.0
        self._sell_volume = 0.0
        self._current_bucket_volume = 0.0
        self._buckets: deque = deque(maxlen=num_buckets)

    def update(self, trade_price: float, prev_price: float, volume: float) -> float:
        """Classify trade via tick rule and update VPIN."""
        is_buy = trade_price >= prev_price

        if is_buy:
            self._buy_volume += volume
        else:
            self._sell_volume += volume
        self._current_bucket_volume += volume

        if self._current_bucket_volume >= self._bucket_volume:
            self._buckets.append((self._buy_volume, self._sell_volume))
            self._buy_volume = 0.0
            self._sell_volume = 0.0
            self._current_bucket_volume = 0.0

        return self._compute()

    def value(self) -> float:
        return self._compute()

    def _compute(self) -> float:
        if not self._buckets:
            return 0.0
        total_imbalance = 0.0
        total_volume = 0.0
        for buy, sell in self._buckets:
            total_imbalance += abs(buy - sell)
            total_volume += buy + sell
        if total_volume < 1e-10:
            return 0.0
        return min(1.0, max(0.0, total_imbalance / total_volume))


class KyleLambda:
    """Kyle's Lambda — price impact coefficient (Kyle 1985).

    lambda = Cov(delta_P, SignedFlow) / Var(SignedFlow)
    """

    def __init__(self, window_size: int):
        self._price_changes: deque = deque(maxlen=window_size)
        self._signed_flows: deque = deque(maxlen=window_size)
        self._prev_mid = 0.0
        self._initialized = False

    def update(self, mid_price: float, signed_trade_size: float) -> float:
        if not self._initialized:
            self._prev_mid = mid_price
            self._initialized = True
            return 0.0

        delta_p = mid_price - self._prev_mid
        self._prev_mid = mid_price

        self._price_changes.append(delta_p)
        self._signed_flows.append(signed_trade_size)

        return self._compute()

    def lambda_(self) -> float:
        return self._compute()

    def _compute(self) -> float:
        n = len(self._price_changes)
        if n < 10:
            return 0.0

        nf = float(n)
        mean_dp = sum(self._price_changes) / nf
        mean_sf = sum(self._signed_flows) / nf

        cov = 0.0
        var_sf = 0.0
        for i in range(n):
            dp_dev = self._price_changes[i] - mean_dp
            sf_dev = self._signed_flows[i] - mean_sf
            cov += dp_dev * sf_dev
            var_sf += sf_dev * sf_dev

        if var_sf < 1e-15:
            return 0.0
        return max(0.0, cov / var_sf)
