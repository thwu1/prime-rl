

class KTBettor:
    """Sequential betting strategy with wealth guarantees."""

    def __init__(self, epsilon=0.0):
        self._wealth_val = 1.0
        self._coin_sum = 0.0
        self._count = 0
        self._epsilon = epsilon

    def bet(self):
        denom = self._count + 1.0 + 2.0 * self._epsilon
        return self._coin_sum / denom

    def update(self, coin):
        b = self.bet()
        self._wealth_val *= (1.0 + b * coin)
        self._coin_sum += coin
        self._count += 1

    def wealth(self):
        return self._wealth_val
