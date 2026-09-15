"""Fixed LLM inference scheduler with FCFS and priority policies."""

import heapq
from typing import Dict, List, Optional
from kv_types import Request, RequestStatus, SchedulerPolicy, ScheduleResult
from kv_cache_manager import KVCacheManager


class Scheduler:
    """Inference scheduler managing request lifecycle."""

    def __init__(self, kv_cache_manager: KVCacheManager,
                 policy: SchedulerPolicy = SchedulerPolicy.FCFS,
                 token_budget: int = 2048,
                 chunk_size: Optional[int] = None):
        self.kv_cache_manager = kv_cache_manager
        self.policy = policy
        self.token_budget = token_budget
        self.chunk_size = chunk_size
        self._waiting_list: List[Request] = []
        self._waiting_heap: List = []
        self._running: Dict[str, Request] = {}
        self._requests: Dict[str, Request] = {}
        self._arrival_counter = 0

    @property
    def num_waiting(self) -> int:
        if self.policy == SchedulerPolicy.FCFS:
            return len(self._waiting_list)
        return len(self._waiting_heap)

    @property
    def num_running(self) -> int:
        return len(self._running)

    def _push_waiting(self, request: Request):
        if self.policy == SchedulerPolicy.FCFS:
            self._waiting_list.append(request)
        else:
            heapq.heappush(self._waiting_heap,
                           (-request.priority, request.arrival_order, request))

    def _get_waiting_ordered(self) -> List[Request]:
        if self.policy == SchedulerPolicy.FCFS:
            return list(self._waiting_list)
        return [r for _, _, r in sorted(self._waiting_heap)]

    def add_request(self, request: Request):
        request.arrival_order = self._arrival_counter
        self._arrival_counter += 1
        request.status = RequestStatus.WAITING
        self._requests[request.request_id] = request
        self._push_waiting(request)

    def schedule(self) -> ScheduleResult:
        result = ScheduleResult()
        budget = self.token_budget
        mgr = self.kv_cache_manager

        # Phase 1: running requests (decode / continued prefill)
        running_snapshot = list(self._running.values())
        if self.policy == SchedulerPolicy.PRIORITY:
            running_snapshot.sort(key=lambda r: (-r.priority, r.arrival_order))

        for request in running_snapshot:
            if budget <= 0:
                break
            if request.request_id not in self._running:
                continue

            if request.num_computed_tokens < len(request.token_ids):
                # Continued (chunked) prefill
                remaining = len(request.token_ids) - request.num_computed_tokens
                num_tokens = min(remaining, budget)
                if self.chunk_size is not None:
                    num_tokens = min(num_tokens, self.chunk_size)
                success = mgr.allocate_slots(request, num_tokens)
                if success:
                    request.num_computed_tokens += num_tokens
                    result.prefill_requests.append(
                        (request.request_id, num_tokens, 0))
                    budget -= num_tokens
            else:
                # Decode step (1 new token)
                num_tokens = 1
                success = mgr.allocate_slots(request, num_tokens)
                if not success:
                    preempted = self._preempt(request)
                    result.preempted_requests.extend(preempted)
                    if preempted:
                        success = mgr.allocate_slots(request, num_tokens)
                if success:
                    result.decode_requests.append(
                        (request.request_id, num_tokens))
                    budget -= num_tokens

        # Phase 2: waiting requests (new prefill)
        scheduled: List[Request] = []
        for request in self._get_waiting_ordered():
            if budget <= 0:
                break

            mgr.hash_request_tokens(request)
            num_computed_blocks = mgr.find_longest_cache_hit(request)
            computed_tokens = num_computed_blocks * mgr.block_size
            remaining = len(request.token_ids) - computed_tokens

            num_tokens = min(remaining, budget)
            if self.chunk_size is not None:
                num_tokens = min(num_tokens, self.chunk_size)
            if num_tokens <= 0 and num_computed_blocks == 0:
                continue

            saved_ct = request.num_computed_tokens
            request.num_computed_tokens = computed_tokens

            success = mgr.allocate_slots(
                request, num_tokens, num_computed_blocks)

            if not success:
                request.num_computed_tokens = saved_ct
                break

            request.num_computed_tokens = computed_tokens + num_tokens
            request.status = RequestStatus.RUNNING
            self._running[request.request_id] = request
            mgr.cache_blocks(request.request_id)

            result.prefill_requests.append(
                (request.request_id, num_tokens, num_computed_blocks))
            budget -= num_tokens
            scheduled.append(request)

        for req in scheduled:
            if self.policy == SchedulerPolicy.FCFS:
                self._waiting_list.remove(req)
            else:
                self._waiting_heap = [
                    entry for entry in self._waiting_heap
                    if entry[2].request_id != req.request_id
                ]
                heapq.heapify(self._waiting_heap)

        result.total_tokens = self.token_budget - budget
        return result

    def _preempt(self, requesting: Request) -> List[str]:
        """Preempt running requests to free blocks for a decode."""
        preempted: List[str] = []
        mgr = self.kv_cache_manager

        total_tokens = requesting.num_computed_tokens + 1
        total_blocks = (total_tokens + mgr.block_size - 1) // mgr.block_size
        current_blocks = mgr.get_num_allocated_blocks(requesting.request_id)
        blocks_needed = total_blocks - current_blocks
        if blocks_needed <= 0:
            return preempted

        candidates = [
            r for r in self._running.values()
            if r.request_id != requesting.request_id
        ]
        if self.policy == SchedulerPolicy.PRIORITY:
            candidates.sort(key=lambda r: (r.priority, -r.arrival_order))
        else:
            candidates.sort(key=lambda r: -r.arrival_order)

        for candidate in candidates:
            if mgr.num_free_blocks >= blocks_needed:
                break
            candidate.status = RequestStatus.PREEMPTED
            candidate.num_computed_tokens = 0
            candidate.output_token_ids = []
            mgr.free(candidate.request_id)
            del self._running[candidate.request_id]
            self._push_waiting(candidate)
            preempted.append(candidate.request_id)

        return preempted

    def update_after_step(self, request_id: str, new_token_id: int = None):
        request = self._requests.get(request_id)
        if request is None:
            return
        if new_token_id is not None:
            request.output_token_ids.append(new_token_id)
            request.num_computed_tokens += 1

    def finish_request(self, request_id: str):
        request = self._requests.get(request_id)
        if request is None:
            return
        request.status = RequestStatus.FINISHED
        self.kv_cache_manager.free(request_id)
        self._running.pop(request_id, None)
