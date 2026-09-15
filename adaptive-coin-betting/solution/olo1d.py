
from .kt_bettor import KTBettor


class OneDimOLO:
    """1-d unconstrained online linear optimization."""

    def __init__(self, lipschitz=1.0):
        self._lipschitz = lipschitz
        self._bettor = KTBettor()
        self._cum_loss = 0.0
        self._grad_sum = 0.0

    def predict(self):
        pred = self._bettor.wealth() * self._bettor.bet()
        return max(-50.0, min(50.0, pred))

    def update(self, grad):
        x = self.predict()
        self._cum_loss += grad * x
        self._grad_sum += grad
        coin = -grad / self._lipschitz
        coin = max(-1.0, min(1.0, coin))
        self._bettor.update(coin)

    def cumulative_regret(self, competitor):
        return self._cum_loss - competitor * self._grad_sum
