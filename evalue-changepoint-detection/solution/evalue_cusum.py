
"""
CUSUM e-procedure for sequential change-point detection.

Implements the multiplicative CUSUM:
  Z_0 = 1
  Z_t = max(Z_{t-1} * e_t, 1)
  Alarm when Z_t >= threshold, then reset.
"""


class CusumDetector:
    def __init__(self, threshold=20.0):
        if threshold <= 1:
            raise ValueError("Threshold must be > 1")
        self.threshold = threshold
        self.reset()

    def reset(self):
        self._stat = 1.0
        self._alarms = []
        self._t = 0

    def update(self, e_value):
        self._t += 1
        self._stat = max(self._stat * e_value, 1.0)

        if self._stat >= self.threshold:
            alarm_time = self._t
            self._alarms.append(alarm_time)
            self._stat = 1.0
            return alarm_time
        return None

    def get_statistic(self):
        return self._stat

    def get_alarms(self):
        return list(self._alarms)
