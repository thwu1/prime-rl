
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PreemptionMode(Enum):
    SWAP = "swap"
    RECOMPUTE = "recompute"


@dataclass
class BlockManagerConfig:
    num_gpu_blocks: int
    num_cpu_blocks: int
    block_size: int
    enable_prefix_caching: bool = False
    preemption_mode: PreemptionMode = PreemptionMode.SWAP


@dataclass
class SequenceStatus:
    seq_id: int
    num_logical_blocks: int
    num_tokens: int
    is_swapped: bool
    block_table: list


@dataclass
class MemorySnapshot:
    gpu_blocks_used: int
    gpu_blocks_free: int
    gpu_blocks_cached: int
    cpu_blocks_used: int
    cpu_blocks_free: int
    num_active_sequences: int
    num_swapped_sequences: int
    prefix_cache_hits: int
    prefix_cache_misses: int
    cow_copies: int


class BlockManagerInterface(ABC):

    @abstractmethod
    def __init__(self, config: BlockManagerConfig): ...

    @abstractmethod
    def allocate(self, seq_id: int, token_ids: list) -> bool: ...

    @abstractmethod
    def append_tokens(self, seq_id: int, token_ids: list) -> bool: ...

    @abstractmethod
    def fork(self, parent_seq_id: int, child_seq_id: int) -> bool: ...

    @abstractmethod
    def free(self, seq_id: int) -> None: ...

    @abstractmethod
    def swap_out(self, seq_id: int) -> bool: ...

    @abstractmethod
    def swap_in(self, seq_id: int) -> bool: ...

    @abstractmethod
    def get_sequence_status(self, seq_id: int) -> Optional[SequenceStatus]: ...

    @abstractmethod
    def get_memory_snapshot(self) -> MemorySnapshot: ...

    @abstractmethod
    def can_allocate(self, num_tokens: int) -> bool: ...

    @abstractmethod
    def get_num_free_gpu_blocks(self) -> int: ...

    @abstractmethod
    def get_num_free_cpu_blocks(self) -> int: ...

    @abstractmethod
    def select_preemption_victim(self) -> Optional[int]: ...
