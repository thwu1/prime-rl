"""
L1 Cache Controller - MOESI Protocol

Implements the L1 cache state machine for the MOESI_CMP_Directory protocol.
Handles load/store requests from the core and protocol messages from L2.
"""

from typing import Dict, List, Optional, Tuple
from .types import (
    CacheState, L1TransientState, MessageType, Message,
    CacheLine, BLOCK_SIZE, BLOCK_OFFSET_BITS, block_addr,
)


class L1Controller:
    """L1 cache controller implementing MOESI protocol transitions."""

    def __init__(self, core_id: int, size_kb: int = 32, assoc: int = 8):
        self.core_id = core_id
        self.size_bytes = size_kb * 1024
        self.assoc = assoc
        self.num_sets = self.size_bytes // (BLOCK_SIZE * assoc)
        self.set_mask = self.num_sets - 1

        # Cache storage: set_index -> list of CacheLine
        self.sets: Dict[int, List[CacheLine]] = {}
        for i in range(self.num_sets):
            self.sets[i] = []

        # Transient state tracking: block_addr -> transient state
        self.transient_states: Dict[int, L1TransientState] = {}

        # Outgoing message queue
        self.outgoing: List[Message] = []

        # Statistics
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "upgrades": 0,
        }

    def _get_set_index(self, addr: int) -> int:
        return (addr >> BLOCK_OFFSET_BITS) & self.set_mask

    def _find_line(self, addr: int) -> Optional[CacheLine]:
        baddr = block_addr(addr)
        set_idx = self._get_set_index(addr)
        for line in self.sets[set_idx]:
            if line.addr == baddr and line.state != CacheState.I:
                return line
        return None

    def _find_victim(self, addr: int) -> Optional[CacheLine]:
        """Find LRU victim in the set. Returns None if set not full."""
        set_idx = self._get_set_index(addr)
        lines = self.sets[set_idx]
        if len(lines) < self.assoc:
            return None
        # LRU: first element is oldest
        return lines[0]

    def _evict_line(self, line: CacheLine) -> None:
        """Initiate eviction of a cache line."""
        baddr = line.addr
        if line.state in (CacheState.M, CacheState.O):
            # Dirty eviction: must writeback
            self.transient_states[baddr] = L1TransientState.MI
            self.outgoing.append(Message(
                msg_type=MessageType.L1_PUTX,
                addr=baddr,
                sender=self.core_id,
                dest=-1,  # L2 bank determined by interleaving
                data=None,
            ))
        elif line.state in (CacheState.E, CacheState.S):
            # Clean eviction: notify L2
            self.outgoing.append(Message(
                msg_type=MessageType.L1_PUTS,
                addr=baddr,
                sender=self.core_id,
                dest=-1,
            ))
            line.state = CacheState.I
        self.stats["evictions"] += 1

    def load(self, addr: int) -> Tuple[bool, Optional[bytes]]:
        """
        Process a load request from the core.
        Returns (hit, data). If miss, sends GETS to L2.
        """
        line = self._find_line(addr)
        if line is not None:
            # Hit in M, O, E, or S state
            self.stats["hits"] += 1
            # Move to MRU position
            set_idx = self._get_set_index(addr)
            self.sets[set_idx].remove(line)
            self.sets[set_idx].append(line)
            return True, line.data

        # Miss
        baddr = block_addr(addr)
        if baddr in self.transient_states:
            # Already waiting for this line
            return False, None

        self.stats["misses"] += 1

        # Check if we need to evict
        victim = self._find_victim(addr)
        if victim is not None and victim.state != CacheState.I:
            self._evict_line(victim)

        # Send GETS to L2
        self.transient_states[baddr] = L1TransientState.IS
        self.outgoing.append(Message(
            msg_type=MessageType.GETS,
            addr=baddr,
            sender=self.core_id,
            dest=-1,
        ))
        return False, None

    def store(self, addr: int, data: bytes) -> bool:
        """
        Process a store request from the core.
        Returns True if hit (can write immediately).
        """
        line = self._find_line(addr)
        if line is not None:
            if line.state == CacheState.M:
                # Already exclusive and dirty - write directly
                line.data = data
                self.stats["hits"] += 1
                return True
            elif line.state == CacheState.E:
                # Exclusive clean - can silently upgrade to M
                line.state = CacheState.M
                line.dirty = True
                line.data = data
                self.stats["hits"] += 1
                return True
            elif line.state in (CacheState.S, CacheState.O):
                # Need upgrade
                baddr = block_addr(addr)
                self.transient_states[baddr] = L1TransientState.SM
                self.outgoing.append(Message(
                    msg_type=MessageType.UPGRADE,
                    addr=baddr,
                    sender=self.core_id,
                    dest=-1,
                ))
                self.stats["upgrades"] += 1
                return False

        # Miss - need exclusive copy
        baddr = block_addr(addr)
        if baddr in self.transient_states:
            return False

        self.stats["misses"] += 1

        victim = self._find_victim(addr)
        if victim is not None and victim.state != CacheState.I:
            self._evict_line(victim)

        self.transient_states[baddr] = L1TransientState.IM
        self.outgoing.append(Message(
            msg_type=MessageType.GETX,
            addr=baddr,
            sender=self.core_id,
            dest=-1,
        ))
        return False

    def handle_response(self, msg: Message) -> None:
        """Handle a response message from L2."""
        baddr = msg.addr
        tstate = self.transient_states.get(baddr)

        if msg.msg_type == MessageType.DATA_S:
            if tstate == L1TransientState.IS:
                # Install line in S state
                self._install_line(baddr, CacheState.S, msg.data)
                del self.transient_states[baddr]
            else:
                raise ProtocolError(
                    f"L1[{self.core_id}] unexpected DATA_S in state {tstate} "
                    f"for addr 0x{baddr:x}"
                )

        elif msg.msg_type == MessageType.DATA_E:
            if tstate == L1TransientState.IS:
                self._install_line(baddr, CacheState.E, msg.data)
                del self.transient_states[baddr]
            elif tstate == L1TransientState.IM:
                self._install_line(baddr, CacheState.M, msg.data, dirty=True)
                del self.transient_states[baddr]
            elif tstate == L1TransientState.SM:
                # Upgrade complete
                line = self._find_line(baddr)
                if line:
                    line.state = CacheState.M
                    line.dirty = True
                del self.transient_states[baddr]
            else:
                raise ProtocolError(
                    f"L1[{self.core_id}] unexpected DATA_E in state {tstate} "
                    f"for addr 0x{baddr:x}"
                )

        elif msg.msg_type == MessageType.WB_ACK:
            if tstate == L1TransientState.MI:
                # Writeback complete - send dirty data
                line = self._find_line_any_state(baddr)
                if line:
                    self.outgoing.append(Message(
                        msg_type=MessageType.L1_WBDIRTYDATA,
                        addr=baddr,
                        sender=self.core_id,
                        dest=msg.sender,
                        data=line.data,
                    ))
                    line.state = CacheState.I
                del self.transient_states[baddr]
            elif tstate == L1TransientState.OI:
                line = self._find_line_any_state(baddr)
                if line:
                    self.outgoing.append(Message(
                        msg_type=MessageType.L1_WBDIRTYDATA,
                        addr=baddr,
                        sender=self.core_id,
                        dest=msg.sender,
                        data=line.data,
                    ))
                    line.state = CacheState.I
                del self.transient_states[baddr]

        elif msg.msg_type == MessageType.INV:
            # Invalidation from L2
            line = self._find_line(baddr)
            if line:
                line.state = CacheState.I
            if baddr in self.transient_states:
                del self.transient_states[baddr]

    def _install_line(self, baddr: int, state: CacheState,
                      data: Optional[bytes], dirty: bool = False) -> None:
        """Install a new cache line, evicting victim if needed."""
        set_idx = self._get_set_index(baddr)
        lines = self.sets[set_idx]

        # Remove any existing invalid entry for this address
        lines[:] = [l for l in lines if l.addr != baddr or l.state != CacheState.I]

        # Remove victim if set is full
        if len(lines) >= self.assoc:
            lines.pop(0)

        line = CacheLine(addr=baddr, state=state, data=data, dirty=dirty)
        lines.append(line)

    def _find_line_any_state(self, baddr: int) -> Optional[CacheLine]:
        """Find line regardless of state (for writeback)."""
        set_idx = self._get_set_index(baddr)
        for line in self.sets[set_idx]:
            if line.addr == baddr:
                return line
        return None

    def drain_messages(self) -> List[Message]:
        msgs = self.outgoing[:]
        self.outgoing.clear()
        return msgs


class ProtocolError(Exception):
    """Raised when a protocol violation is detected."""
    pass
