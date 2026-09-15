
from dataclasses import dataclass
import config


@dataclass
class Request:
    """An LLM inference request with autoregressive token generation and SLO tier."""
    id: int
    arrival_time: float      # ms, when the request enters the system
    input_tokens: int        # known at arrival (prompt length)
    output_tokens: int       # ground truth; NOT visible to the scheduler
    slo_tier: int = 1        # 0=latency-critical, 1=interactive, 2=batch

    # --- runtime state (managed by the simulator) ---
    tokens_generated: int = 0
    prefill_done: bool = False
    start_time: float = -1.0
    completion_time: float = -1.0
    preemption_count: int = 0

    @property
    def is_complete(self) -> bool:
        return self.tokens_generated >= self.output_tokens

    @property
    def total_kv_tokens(self) -> int:
        """Current KV-cache size in tokens (input + generated so far)."""
        if not self.prefill_done:
            return 0
        return self.input_tokens + self.tokens_generated

    @property
    def jct(self) -> float:
        """Job completion time in ms."""
        if self.completion_time < 0:
            return float('inf')
        return self.completion_time - self.arrival_time

    @property
    def optimal_time(self) -> float:
        """Minimum possible processing time (no queuing, no overhead)."""
        return (self.input_tokens * config.PREFILL_TIME_PER_TOKEN_MS +
                self.output_tokens * config.DECODE_TIME_PER_TOKEN_MS)

    @property
    def slo_deadline(self) -> float:
        """Absolute SLO deadline in ms of JCT."""
        return self.optimal_time * config.SLO_DEADLINE_MULTIPLIERS[self.slo_tier]

    @property
    def slo_met(self) -> bool:
        return self.jct <= self.slo_deadline
