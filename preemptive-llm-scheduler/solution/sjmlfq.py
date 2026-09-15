
from collections import deque
from scheduler.base import Scheduler


class SJMLFQScheduler(Scheduler):
    """Skip-Join Multi-Level Feedback Queue scheduler for LLM inference.

    - 4 priority levels with exponentially increasing quanta (16, 32, 64, 128).
    - New requests skip to an initial level based on input token count.
    - Quantum exhaustion demotes by one level; higher-priority preemption
      keeps the current level (no demotion penalty for involuntary preemption).
    - The finite workload guarantees all levels drain without explicit boosting.
    """

    NUM_LEVELS = 4
    BASE_QUANTUM = 16                    # tokens at level 0
    SKIP_THRESHOLDS = [50, 200, 800]     # input-token boundaries for levels 0-2

    def __init__(self):
        self.queues = [deque() for _ in range(self.NUM_LEVELS)]
        self.current = None
        self.current_level = 0
        self.tokens_in_quantum = 0
        self.request_levels = {}         # request id -> current level
        self._preempt_reason = "quantum"

    # ---- helpers ----

    def _initial_level(self, request):
        for lvl, thr in enumerate(self.SKIP_THRESHOLDS):
            if request.input_tokens <= thr:
                return lvl
        return self.NUM_LEVELS - 1

    def _quantum(self, level):
        return self.BASE_QUANTUM * (2 ** level)

    # ---- Scheduler interface ----

    def add_request(self, request):
        lvl = self._initial_level(request)
        self.request_levels[request.id] = lvl
        self.queues[lvl].append(request)

    def get_next(self):
        if self.current is not None and not self.current.is_complete:
            return self.current
        for lvl in range(self.NUM_LEVELS):
            if self.queues[lvl]:
                self.current = self.queues[lvl].popleft()
                self.current_level = self.request_levels[self.current.id]
                self.tokens_in_quantum = 0
                return self.current
        self.current = None
        return None

    def on_token_generated(self, request):
        self.tokens_in_quantum += 1

        # Higher-priority arrival -> preempt without demotion
        for lvl in range(self.current_level):
            if self.queues[lvl]:
                self._preempt_reason = "priority"
                return False

        # Quantum exhausted -> preempt with demotion (only if others waiting)
        if self.tokens_in_quantum >= self._quantum(self.current_level):
            if any(self.queues[l] for l in range(self.NUM_LEVELS)):
                self._preempt_reason = "quantum"
                return False

        return True

    def on_preempt(self, request):
        if self._preempt_reason == "quantum":
            next_lvl = min(self.current_level + 1, self.NUM_LEVELS - 1)
        else:
            next_lvl = self.current_level

        self.request_levels[request.id] = next_lvl
        self.queues[next_lvl].append(request)
        self.current = None
        self.tokens_in_quantum = 0

    def on_complete(self, request):
        self.request_levels.pop(request.id, None)
        self.current = None
        self.tokens_in_quantum = 0

    def has_pending(self):
        if self.current is not None and not self.current.is_complete:
            return True
        return any(self.queues[l] for l in range(self.NUM_LEVELS))
