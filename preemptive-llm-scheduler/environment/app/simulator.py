
import copy
import json
import os
from typing import List, Optional

import config
from memory_manager import PagedMemoryManager
from request import Request
from scheduler.base import Scheduler


class TraceLogger:
    """Writes scheduling events as JSON Lines for offline analysis."""

    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._file = None
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            self._file = open(path, "w")

    def log(self, event: dict):
        if self._file:
            self._file.write(json.dumps(event, default=str) + "\n")

    def close(self):
        if self._file:
            self._file.close()
            self._file = None


class Simulator:
    """Discrete-event simulator for LLM inference serving with paged KV cache."""

    def __init__(self, scheduler: Scheduler, requests: List[Request],
                 trace_path: Optional[str] = None):
        self.scheduler = scheduler
        self.memory = PagedMemoryManager()
        scheduler.set_memory(self.memory)

        self.pending_arrivals = sorted(
            [copy.deepcopy(r) for r in requests],
            key=lambda r: r.arrival_time,
        )
        self.completed: List[Request] = []
        self.time = 0.0
        self.trace = TraceLogger(trace_path)

    def _drain_arrivals(self):
        while self.pending_arrivals and self.pending_arrivals[0].arrival_time <= self.time:
            req = self.pending_arrivals.pop(0)
            self.scheduler.add_request(req)
            self.trace.log({
                "ts": round(self.time, 4),
                "event": "arrival",
                "req_id": req.id,
                "input_tokens": req.input_tokens,
                "output_tokens": req.output_tokens,
                "slo_tier": req.slo_tier,
            })

    def run(self) -> List[Request]:
        max_iter = 20_000_000
        it = 0
        sample_interval = 200

        while (self.pending_arrivals or self.scheduler.has_pending()) and it < max_iter:
            it += 1
            self._drain_arrivals()

            if it % sample_interval == 0:
                self.memory.sample_fragmentation()

            req = self.scheduler.get_next()
            if req is None:
                if self.pending_arrivals:
                    self.time = self.pending_arrivals[0].arrival_time
                else:
                    break
                continue

            # Load KV-cache pages into GPU
            load_cost = self.memory.load_request(req)
            self.time += load_cost
            self._drain_arrivals()

            self.trace.log({
                "ts": round(self.time, 4),
                "event": "schedule",
                "req_id": req.id,
                "pages": self.memory.get_page_count(req.id),
                "gpu_util": round(self.memory.utilization, 4),
                "frag": round(self.memory.fragmentation, 4),
                "load_cost_ms": round(load_cost, 4),
            })

            # Prefill (runs once per request)
            if not req.prefill_done:
                if req.start_time < 0:
                    req.start_time = self.time
                self.time += req.input_tokens * config.PREFILL_TIME_PER_TOKEN_MS
                req.prefill_done = True
                # Allocate KV-cache pages for the prefilled input tokens
                alloc_cost = self.memory.load_request(req)
                self.time += alloc_cost
                self._drain_arrivals()

            # Decode loop — one output token per iteration
            while not req.is_complete:
                self.time += config.DECODE_TIME_PER_TOKEN_MS
                req.tokens_generated += 1
                update_cost = self.memory.update_kv_cache(req)
                self.time += update_cost
                self._drain_arrivals()

                if not req.is_complete:
                    if not self.scheduler.on_token_generated(req):
                        req.preemption_count += 1
                        self.scheduler.on_preempt(req)
                        self.trace.log({
                            "ts": round(self.time, 4),
                            "event": "preempt",
                            "req_id": req.id,
                            "tokens_generated": req.tokens_generated,
                            "preemption_count": req.preemption_count,
                            "pages": self.memory.get_page_count(req.id),
                        })
                        self.time += config.CONTEXT_SWITCH_OVERHEAD_MS
                        self._drain_arrivals()
                        break

            if req.is_complete:
                req.completion_time = self.time
                self.scheduler.on_complete(req)
                self.memory.free_request(req)
                self.completed.append(req)
                self.trace.log({
                    "ts": round(self.time, 4),
                    "event": "complete",
                    "req_id": req.id,
                    "jct": round(req.jct, 4),
                    "slo_tier": req.slo_tier,
                    "slo_met": req.slo_met,
                    "slo_deadline": round(req.slo_deadline, 4),
                    "preemptions": req.preemption_count,
                })

        self.trace.close()
        return self.completed
