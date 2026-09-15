
from .coord_oco import CoordOCO


class CBCE:
    """Strongly adaptive meta-algorithm using geometric coverings."""

    def __init__(self, dim, lipschitz=1.0):
        self._dim = dim
        self._lipschitz = lipschitz
        self._t = 0
        self._learners = {}
        self._all_grads = []
        self._all_preds = []

    def _active_keys(self, t):
        """Return (scale, block_index) tuples for active dyadic intervals at time t."""
        keys = []
        k = 0
        while True:
            block_size = 1 << k
            j = t // block_size
            keys.append((k, j))
            if block_size > t + 1:
                break
            k += 1
        return keys

    def predict(self):
        t = self._t
        keys = self._active_keys(t)
        for key in keys:
            if key not in self._learners:
                self._learners[key] = CoordOCO(self._dim, self._lipschitz)

        combined = [0.0] * self._dim
        total_w = 0.0
        for key in keys:
            scale = key[0]
            w = 1.0 / (1 << scale)
            pred = self._learners[key].predict()
            for d in range(self._dim):
                combined[d] += w * pred[d]
            total_w += w

        if total_w > 0:
            for d in range(self._dim):
                combined[d] /= total_w

        return combined

    def update(self, grad):
        pred = self.predict()
        self._all_preds.append(list(pred))
        self._all_grads.append(list(grad))

        keys = self._active_keys(self._t)
        for key in keys:
            if key in self._learners:
                self._learners[key].update(grad)

        self._t += 1

        # Remove expired learners (not active in next round)
        next_keys = set(self._active_keys(self._t))
        expired = [k for k in self._learners if k not in next_keys]
        for k in expired:
            del self._learners[k]

    def interval_regret(self, start, end, competitor):
        """Linearized regret on [start, end) against a fixed competitor."""
        regret = 0.0
        for t in range(start, end):
            if t < len(self._all_grads):
                g = self._all_grads[t]
                p = self._all_preds[t]
                for d in range(self._dim):
                    regret += g[d] * (p[d] - competitor[d])
        return regret

    def num_active_learners(self):
        if self._t == 0:
            return 0
        return len(self._active_keys(self._t - 1))
