"""Shared types for the paged KV-cache allocator system.

DO NOT MODIFY THIS FILE.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Tuple


class RequestStatus(Enum):
    WAITING = "waiting"
    RUNNING = "running"
    FINISHED = "finished"
    PREEMPTED = "preempted"


class SchedulerPolicy(Enum):
    FCFS = "fcfs"
    PRIORITY = "priority"


@dataclass
class BlockHash:
    """Hash of a block's token content for prefix caching."""
    hash_value: int
    token_ids: tuple


@dataclass
class Block:
    """A KV-cache block."""
    block_id: int
    ref_count: int = 0
    block_hash: Optional[BlockHash] = None
    prev_free: Optional['Block'] = None
    next_free: Optional['Block'] = None
    _in_free_queue: bool = False


@dataclass
class Request:
    """An inference request."""
    request_id: str
    token_ids: List[int]
    priority: float = 0.0
    arrival_order: int = 0
    status: RequestStatus = RequestStatus.WAITING
    num_computed_tokens: int = 0
    output_token_ids: List[int] = field(default_factory=list)
    max_tokens: int = 100


@dataclass
class ScheduleResult:
    """Result of a single scheduler step."""
    # (request_id, num_tokens) for decode requests
    decode_requests: List[Tuple[str, int]] = field(default_factory=list)
    # (request_id, num_tokens, num_computed_blocks) for prefill requests
    prefill_requests: List[Tuple[str, int, int]] = field(default_factory=list)
    # request_ids preempted this step
    preempted_requests: List[str] = field(default_factory=list)
    # total tokens scheduled
    total_tokens: int = 0
