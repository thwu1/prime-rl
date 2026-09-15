"""Type definitions for the MOESI cache coherence simulator."""


from enum import Enum, auto
from dataclasses import dataclass, field


class CacheState(Enum):
    """MOESI cache line states."""
    MODIFIED = auto()
    OWNED = auto()
    EXCLUSIVE = auto()
    SHARED = auto()
    INVALID = auto()


class DirState(Enum):
    """Directory entry states."""
    UNCACHED = auto()
    SHARED = auto()
    EXCLUSIVE_MODIFIED = auto()


@dataclass
class CacheLine:
    """A single cache line."""
    state: CacheState = CacheState.INVALID
    tag: int = -1
    data: int = 0


@dataclass
class DirEntry:
    """A directory entry tracking coherence state for one memory block."""
    state: DirState = DirState.UNCACHED
    owner: int = -1
    sharers: set = field(default_factory=set)
    data: int = 0
