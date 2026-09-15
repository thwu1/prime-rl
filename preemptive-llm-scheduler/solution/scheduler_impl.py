
"""Paged-attention-aware MLFQ scheduler with SLO-tier prioritization.

Design decisions:
- 4 priority levels with exponentially increasing quanta (16, 32, 64, 128 tokens).
- Skip-join initial placement based on input token count:
  <=50 -> level 0,  <=200 -> level 1,  <=800 -> level 2,  else level 3.
- SLO tier-0 (latency-critical) requests get a one-level priority boost.
- Quantum exhaustion demotes by one level; priority preemption keeps current level.
- Memory-pressure-aware preemption gating: skip preemption when the current
  request's swap cost exceeds a threshold, avoiding cascading page evictions
  in the tight 256-page GPU memory.
"""

from collections import deque
from scheduler.base import Scheduler


class PagedMLFQScheduler(Scheduler):

    NUM_LEVELS = 4
    BASE_QUANTUM = 16
    SKIP_THRESHOLDS = [50, 200, 800]
    SWAP_COST_GATE_MS = 80.0   # Skip preemption if swap cost exceeds this

    def __init__(self):
        self.queues = [deque() for _ in range(self.NUM_LEVELS)]
        self.current = None
        self.current_level = 0
        self.tokens_in_quantum = 0
        self.request_levels = {}
        self._preempt_reason = "quantum"

    # ---- helpers ----

    def _initial_level(self, request):
        base = self.NUM_LEVELS - 1
        for lvl, thr in enumerate(self.SKIP_THRESHOLDS):
            if request.input_tokens <= thr:
                base = lvl
                break
        # SLO tier-0 boost
        if hasattr(request, "slo_tier") and request.slo_tier == 0:
            base = max(0, base - 1)
        return base

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

        # Priority preemption: higher-priority arrival present
        for lvl in range(self.current_level):
            if self.queues[lvl]:
                # Memory-pressure gating: avoid preempting if swap cost is high
                if hasattr(self, "_memory") and self._memory is not None:
                    cost = self._memory.get_swap_cost(request.id)
                    if cost > self.SWAP_COST_GATE_MS:
                        continue
                self._preempt_reason = "priority"
                return False

        # Quantum exhaustion
        if self.tokens_in_quantum >= self._quantum(self.current_level):
            if any(self.queues[l] for l in range(self.NUM_LEVELS)):
                self._preempt_reason = "quantum"
                return False

        return True

    def on_preempt(self, request):
        if self._preempt_reason == "quantum":
            next_lvl = min(self.current_level + 1, self.NUM_LEVELS - 1)
        else:
            next_lvl = self.current_level  # no demotion on priority preemption

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
