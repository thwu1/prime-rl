
from .olo1d import OneDimOLO


class CoordOCO:
    """d-dimensional coordinate-wise online convex optimization."""

    def __init__(self, dim, lipschitz=1.0):
        self._dim = dim
        self._learners = [OneDimOLO(lipschitz=lipschitz) for _ in range(dim)]

    def predict(self):
        return [self._learners[d].predict() for d in range(self._dim)]

    def update(self, grad):
        for d in range(self._dim):
            self._learners[d].update(grad[d])

    def cumulative_regret(self, competitor):
        return sum(
            self._learners[d].cumulative_regret(competitor[d])
            for d in range(self._dim)
        )
