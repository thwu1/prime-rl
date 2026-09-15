"""Adverse selection and toxicity detection via EMA-smoothed post-fill analysis."""

from collections import deque


class ToxicityDetector:
    def __init__(self, alpha=0.15, warn_threshold=0.35, halt_threshold=0.65,
                 adverse_move_threshold=0.5, max_history=200):
        self.alpha = alpha
        self.warn_threshold = warn_threshold
        self.halt_threshold = halt_threshold
        self.adverse_move_threshold = adverse_move_threshold
        self.fills = deque(maxlen=max_history)
        self._toxicity = 0.0
        self.consecutive_toxic = 0
        self.total_evaluated = 0
        self.total_toxic = 0

    def record_fill(self, price, is_bid, timestamp):
        self.fills.append({
            'price': price,
            'is_bid': is_bid,
            'timestamp': timestamp,
            'evaluated': False,
        })

    def evaluate(self, fair_value, timestamp):
        for fill in self.fills:
            if fill['evaluated']:
                continue

            if fill['is_bid']:
                post_move = fair_value - fill['price']
            else:
                post_move = fill['price'] - fair_value

            fill['evaluated'] = True
            is_toxic = post_move > self.adverse_move_threshold

            self.total_evaluated += 1
            if is_toxic:
                self.total_toxic += 1
                self.consecutive_toxic += 1
            else:
                self.consecutive_toxic = 0

            toxic_signal = 1.0 if is_toxic else 0.0
            self._toxicity = (self.alpha * toxic_signal
                              + (1 - self.alpha) * self._toxicity)

        return self._recommend()

    def _recommend(self):
        if self._toxicity > self.halt_threshold or self.consecutive_toxic >= 5:
            return 'HaltPassive'
        elif self._toxicity > self.warn_threshold:
            return 'Widen'
        return 'Normal'

    def toxicity(self):
        return self._toxicity

    def is_safe(self):
        return self._toxicity < self.warn_threshold
