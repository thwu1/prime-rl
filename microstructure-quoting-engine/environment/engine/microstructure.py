"""Market microstructure signals: microprice, order flow imbalance, VPIN, Kyle's lambda."""

from collections import deque


def microprice(bid, ask, bid_size, ask_size):
    """Size-weighted mid-price estimator."""
    total = bid_size + ask_size
    if total < 1e-10:
        return (bid + ask) / 2.0
    return bid * (bid_size / total) + ask * (ask_size / total)


class OrderFlowImbalance:
    """Normalized order flow imbalance from bid/ask level changes."""

    def __init__(self, window_size=10):
        self.prev_bid_price = 0.0
        self.prev_bid_size = 0.0
        self.prev_ask_price = 0.0
        self.prev_ask_size = 0.0
        self.window = deque(maxlen=window_size)
        self.initialized = False

    def update(self, bid_price, bid_size, ask_price, ask_size):
        if not self.initialized:
            self.prev_bid_price = bid_price
            self.prev_bid_size = bid_size
            self.prev_ask_price = ask_price
            self.prev_ask_size = ask_size
            self.initialized = True
            return 0.0

        if bid_price > self.prev_bid_price:
            delta_bid = bid_size
        elif bid_price == self.prev_bid_price:
            delta_bid = bid_size - self.prev_bid_size
        else:
            delta_bid = -self.prev_bid_size

        if ask_price < self.prev_ask_price:
            delta_ask = ask_size
        elif ask_price == self.prev_ask_price:
            delta_ask = ask_size - self.prev_ask_size
        else:
            delta_ask = -self.prev_ask_size

        ofi_tick = delta_ask - delta_bid
        self.window.append(ofi_tick)

        self.prev_bid_price = bid_price
        self.prev_bid_size = bid_size
        self.prev_ask_price = ask_price
        self.prev_ask_size = ask_size

        total = sum(self.window)
        abs_total = sum(abs(x) for x in self.window)
        if abs_total > 0:
            return total / abs_total
        return 0.0

    def raw_ofi(self):
        return sum(self.window)


class Vpin:
    """Volume-synchronized probability of informed trading."""

    def __init__(self, bucket_volume=1000.0, num_buckets=10):
        self.bucket_volume = bucket_volume
        self.num_buckets = num_buckets
        self.buy_volume = 0.0
        self.sell_volume = 0.0
        self.current_bucket_volume = 0.0
        self.buckets = deque(maxlen=num_buckets)

    def update(self, trade_price, prev_price, volume):
        is_buy = trade_price >= prev_price
        if is_buy:
            self.buy_volume += volume
        else:
            self.sell_volume += volume
        self.current_bucket_volume += volume

        if self.current_bucket_volume >= self.bucket_volume:
            self.buckets.append((self.buy_volume, self.sell_volume))
            self.buy_volume = 0.0
            self.sell_volume = 0.0
            self.current_bucket_volume = 0.0

        return self.value()

    def value(self):
        if not self.buckets:
            return 0.0
        total_imbalance = sum(abs(b - s) for b, s in self.buckets)
        total_volume = sum(b + s for b, s in self.buckets)
        if total_volume < 1e-10:
            return 0.0
        return min(1.0, max(0.0, total_imbalance / total_volume))


class KyleLambda:
    """Rolling OLS price-impact coefficient."""

    def __init__(self, window_size=50):
        self.price_changes = deque(maxlen=window_size)
        self.signed_flows = deque(maxlen=window_size)
        self.prev_mid = 0.0
        self.initialized = False

    def update(self, mid_price, signed_trade_size):
        if not self.initialized:
            self.prev_mid = mid_price
            self.initialized = True
            return 0.0

        delta_p = mid_price - self.prev_mid
        self.prev_mid = mid_price

        self.price_changes.append(delta_p)
        self.signed_flows.append(signed_trade_size)

        return self._compute()

    def _compute(self):
        n = len(self.price_changes)
        if n < 10:
            return 0.0

        mean_dp = sum(self.price_changes) / n
        mean_sf = sum(self.signed_flows) / n

        cov = sum(
            (self.price_changes[i] - mean_dp) * (self.signed_flows[i] - mean_sf)
            for i in range(n)
        )
        var_sf = sum((self.signed_flows[i] - mean_sf) ** 2 for i in range(n))

        if var_sf < 1e-15:
            return 0.0
        return max(0.0, cov / var_sf)

    def lambda_value(self):
        return self._compute()
