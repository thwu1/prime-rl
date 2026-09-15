"""
MOESI Cache Coherence Protocol Simulator - Core Types

Defines cache line states, message types, and shared data structures
for the MOESI_CMP_Directory protocol.
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Set


class CacheState(Enum):
    """MOESI cache line states."""
    M = auto()   # Modified - exclusive dirty copy
    O = auto()   # Owned - dirty copy, shared with others
    E = auto()   # Exclusive - clean exclusive copy
    S = auto()   # Shared - clean shared copy
    I = auto()   # Invalid


class L1TransientState(Enum):
    """L1 cache transient states during protocol transactions."""
    STABLE = auto()
    IS = auto()    # Invalid → Shared (waiting for data)
    IM = auto()    # Invalid → Modified (waiting for data)
    SM = auto()    # Shared → Modified (waiting for upgrade ack)
    MI = auto()    # Modified → Invalid (writeback in progress)
    OI = auto()    # Owned → Invalid (writeback in progress)
    SI = auto()    # Shared → Invalid (eviction in progress)


class L2State(Enum):
    """L2 cache states including directory-like tracking."""
    M = auto()
    O = auto()
    E = auto()
    S = auto()
    I = auto()
    # Transient states
    ILX = auto()   # Invalid, fetching exclusive from memory
    ILS = auto()   # Invalid, fetching shared from memory
    ILXW = auto()  # ILX, waiting for L1 writeback
    SL = auto()    # Shared, L1 requesting upgrade
    MI = auto()    # Modified → Invalid (writeback to memory)
    OI = auto()    # Owned → Invalid (writeback to memory)


class DirState(Enum):
    """Directory controller states."""
    M = auto()    # One exclusive owner
    O = auto()    # One owner, possibly shared
    S = auto()    # Shared among multiple caches
    I = auto()    # Not cached anywhere
    # Transient states
    MI = auto()   # Modified → Invalid (recall in progress)


class MessageType(Enum):
    """Protocol messages between controllers."""
    # L1 → L2 requests
    GETS = auto()         # Request shared copy
    GETX = auto()         # Request exclusive copy
    UPGRADE = auto()      # Upgrade S→M
    L1_PUTX = auto()      # L1 evicting modified line
    L1_PUTS = auto()      # L1 evicting shared line
    L1_WBDIRTYDATA = auto()  # L1 writeback dirty data

    # L2 → L1 responses
    DATA_S = auto()       # Data in shared state
    DATA_E = auto()       # Data in exclusive state
    INV = auto()          # Invalidation request
    WB_ACK = auto()       # Writeback acknowledgment

    # L2 → Directory requests
    DIR_GETS = auto()
    DIR_GETX = auto()
    DIR_PUTX = auto()     # L2 writeback to memory
    DIR_WB_DATA = auto()  # L2 writeback data

    # Directory → L2 responses
    DIR_DATA_S = auto()
    DIR_DATA_E = auto()
    DIR_WB_ACK = auto()   # Directory writeback ack
    DIR_RECALL = auto()   # Directory recalling line


@dataclass
class CacheLine:
    """A single cache line."""
    addr: int
    state: CacheState = CacheState.I
    data: Optional[bytes] = None
    dirty: bool = False

    def __repr__(self):
        return f"CacheLine(addr=0x{self.addr:x}, state={self.state.name}, dirty={self.dirty})"


@dataclass
class L2CacheLine:
    """L2 cache line with sharer tracking (directory-like)."""
    addr: int
    state: L2State = L2State.I
    data: Optional[bytes] = None
    dirty: bool = False
    sharers: Set[int] = field(default_factory=set)
    owner: int = -1
    # Internal directory entry tracking
    dir_entry_allocated: bool = False

    def __repr__(self):
        return (f"L2CacheLine(addr=0x{self.addr:x}, state={self.state.name}, "
                f"sharers={self.sharers}, owner={self.owner}, dir_alloc={self.dir_entry_allocated})")


@dataclass
class DirEntry:
    """Directory entry tracking which L2 caches hold a line."""
    addr: int
    state: DirState = DirState.I
    owner: int = -1       # L2 bank that owns the line
    sharers: Set[int] = field(default_factory=set)
    data: Optional[bytes] = None

    def __repr__(self):
        return (f"DirEntry(addr=0x{self.addr:x}, state={self.state.name}, "
                f"owner={self.owner}, sharers={self.sharers})")


@dataclass
class Message:
    """Protocol message passed between controllers."""
    msg_type: MessageType
    addr: int
    sender: int
    dest: int
    data: Optional[bytes] = None
    ack_count: int = 0
    timestamp: int = 0

    def __repr__(self):
        return (f"Message({self.msg_type.name}, addr=0x{self.addr:x}, "
                f"src={self.sender}, dst={self.dest})")


# Block size constant (64 bytes, standard cache line)
BLOCK_SIZE = 64
BLOCK_OFFSET_BITS = 6  # log2(64)

def block_addr(addr: int) -> int:
    """Align address to block boundary."""
    return addr & ~(BLOCK_SIZE - 1)
