"""
L2 Cache Controller - MOESI_CMP_Directory Protocol

Implements L2 cache with directory-like sharer tracking.
Handles requests from L1 controllers and communicates with the
directory controller for misses.
"""

import ctypes
import os
from typing import Dict, List, Optional, Set
from .types import (
    L2State, MessageType, Message, L2CacheLine,
    BLOCK_SIZE, BLOCK_OFFSET_BITS, block_addr,
)

# Load native address computation library for set index calculation
_lib_dir = os.path.dirname(os.path.abspath(__file__))
_lib_path = os.path.join(_lib_dir, 'libaddrcalc.so')
_lib = ctypes.CDLL(_lib_path)

_lib.compute_set_index.argtypes = [
    ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32,
]
_lib.compute_set_index.restype = ctypes.c_uint32


class L2Controller:
    """L2 cache controller with embedded directory tracking."""

    def __init__(self, bank_id: int, size_kb: int = 2, assoc: int = 2):
        self.bank_id = bank_id
        self.size_bytes = size_kb * 1024
        self.assoc = assoc
        self.num_sets = self.size_bytes // (BLOCK_SIZE * assoc)
        self.set_mask = self.num_sets - 1

        self.sets: Dict[int, List[L2CacheLine]] = {}
        for i in range(self.num_sets):
            self.sets[i] = []

        # Lines currently being evicted (writeback in progress to directory).
        # Keyed by block address. These have been removed from self.sets
        # but still need to be cleaned up when DIR_WB_ACK arrives.
        self.evicting_lines: Dict[int, L2CacheLine] = {}

        self.outgoing: List[Message] = []
        self.pending_wb: Dict[int, int] = {}  # addr -> requesting core_id

        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "dir_entries_allocated": 0,
            "dir_entries_deallocated": 0,
        }

    def _get_set_index(self, addr: int) -> int:
        return _lib.compute_set_index(addr, self.set_mask, BLOCK_OFFSET_BITS)

    def _find_line(self, addr: int) -> Optional[L2CacheLine]:
        baddr = block_addr(addr)
        set_idx = self._get_set_index(addr)
        for line in self.sets.get(set_idx, []):
            if line.addr == baddr and line.state != L2State.I:
                return line
        return None

    def _allocate_line(self, addr: int) -> L2CacheLine:
        baddr = block_addr(addr)
        set_idx = self._get_set_index(addr)
        lines = self.sets[set_idx]

        # Remove existing invalid entry for this address
        lines[:] = [l for l in lines if l.addr != baddr or l.state != L2State.I]

        if len(lines) >= self.assoc:
            victim = lines.pop(0)
            if victim.state in (L2State.M, L2State.O):
                self._evict_to_dir(victim)
            # If victim is S or E (clean), just drop it

        line = L2CacheLine(addr=baddr, state=L2State.I)
        lines.append(line)
        return line

    def _evict_to_dir(self, line: L2CacheLine) -> None:
        """
        Evict dirty L2 line back to directory/memory.
        Line has already been removed from the cache set.
        It is stored in evicting_lines until DIR_WB_ACK arrives.
        """
        self.stats["evictions"] += 1
        line.state = L2State.MI
        self.evicting_lines[line.addr] = line
        self.outgoing.append(Message(
            msg_type=MessageType.DIR_PUTX,
            addr=line.addr,
            sender=self.bank_id,
            dest=-1,
            data=line.data,
        ))

    def _allocate_dir_entry(self, line: L2CacheLine) -> None:
        """Allocate internal directory entry for tracking sharers."""
        line.dir_entry_allocated = True
        line.sharers = set()
        line.owner = -1
        self.stats["dir_entries_allocated"] += 1

    def _remove_from_dir(self, line: L2CacheLine) -> None:
        """Remove internal directory entry."""
        assert line.dir_entry_allocated, (
            f"L2[{self.bank_id}] assertion failed: attempting to remove "
            f"non-existent directory entry for addr 0x{line.addr:x}. "
            f"Line state: {line.state}, sharers: {line.sharers}"
        )
        line.dir_entry_allocated = False
        line.sharers = set()
        line.owner = -1
        self.stats["dir_entries_deallocated"] += 1

    def _copy_dir_to_cache_and_remove(self, line: L2CacheLine) -> None:
        """
        Copy directory info into the cache entry and deallocate the
        internal directory entry. Used when L2 transitions from a
        transient state to stable state with data.
        """
        # The directory info is now embedded in the cache line itself
        # Deallocate the separate directory tracking
        if line.dir_entry_allocated:
            line.dir_entry_allocated = False
            self.stats["dir_entries_deallocated"] += 1

    def handle_l1_request(self, msg: Message) -> None:
        """Handle a request from an L1 controller."""
        baddr = msg.addr
        line = self._find_line(baddr)

        if msg.msg_type == MessageType.GETS:
            self._handle_gets(msg, line)
        elif msg.msg_type == MessageType.GETX:
            self._handle_getx(msg, line)
        elif msg.msg_type == MessageType.UPGRADE:
            self._handle_upgrade(msg, line)
        elif msg.msg_type == MessageType.L1_PUTX:
            self._handle_l1_putx(msg, line)
        elif msg.msg_type == MessageType.L1_PUTS:
            self._handle_l1_puts(msg, line)
        elif msg.msg_type == MessageType.L1_WBDIRTYDATA:
            self._handle_l1_wbdirtydata(msg, line)

    def _handle_gets(self, msg: Message, line: Optional[L2CacheLine]) -> None:
        """L1 requesting shared copy."""
        baddr = msg.addr

        if line is None:
            # L2 miss - fetch from directory
            line = self._allocate_line(baddr)
            line.state = L2State.ILS
            self._allocate_dir_entry(line)
            line.sharers.add(msg.sender)
            self.outgoing.append(Message(
                msg_type=MessageType.DIR_GETS,
                addr=baddr,
                sender=self.bank_id,
                dest=-1,
            ))
            self.stats["misses"] += 1
            return

        self.stats["hits"] += 1

        if line.state in (L2State.M, L2State.E, L2State.S, L2State.O):
            # Have data - send to L1
            line.sharers.add(msg.sender)
            if len(line.sharers) == 1 and line.state == L2State.E:
                # Only requester - can give exclusive
                self.outgoing.append(Message(
                    msg_type=MessageType.DATA_E,
                    addr=baddr,
                    sender=self.bank_id,
                    dest=msg.sender,
                    data=line.data,
                ))
            else:
                if line.state == L2State.E:
                    line.state = L2State.S
                self.outgoing.append(Message(
                    msg_type=MessageType.DATA_S,
                    addr=baddr,
                    sender=self.bank_id,
                    dest=msg.sender,
                    data=line.data,
                ))

    def _handle_getx(self, msg: Message, line: Optional[L2CacheLine]) -> None:
        """L1 requesting exclusive copy."""
        baddr = msg.addr

        if line is None:
            line = self._allocate_line(baddr)
            line.state = L2State.ILX
            self._allocate_dir_entry(line)
            line.owner = msg.sender
            self.outgoing.append(Message(
                msg_type=MessageType.DIR_GETX,
                addr=baddr,
                sender=self.bank_id,
                dest=-1,
            ))
            self.stats["misses"] += 1
            return

        self.stats["hits"] += 1

        # Invalidate other sharers
        for sharer in line.sharers:
            if sharer != msg.sender:
                self.outgoing.append(Message(
                    msg_type=MessageType.INV,
                    addr=baddr,
                    sender=self.bank_id,
                    dest=sharer,
                ))
        line.sharers = {msg.sender}
        line.owner = msg.sender
        line.state = L2State.M
        self.outgoing.append(Message(
            msg_type=MessageType.DATA_E,
            addr=baddr,
            sender=self.bank_id,
            dest=msg.sender,
            data=line.data,
        ))

    def _handle_upgrade(self, msg: Message, line: Optional[L2CacheLine]) -> None:
        """L1 upgrading from S to M."""
        baddr = msg.addr

        if line is None:
            # Race condition - treat as GETX
            self._handle_getx(msg, line)
            return

        # Invalidate other sharers
        for sharer in line.sharers:
            if sharer != msg.sender:
                self.outgoing.append(Message(
                    msg_type=MessageType.INV,
                    addr=baddr,
                    sender=self.bank_id,
                    dest=sharer,
                ))
        line.sharers = {msg.sender}
        line.owner = msg.sender
        line.state = L2State.M
        self.outgoing.append(Message(
            msg_type=MessageType.DATA_E,
            addr=baddr,
            sender=self.bank_id,
            dest=msg.sender,
            data=line.data,
        ))

    def _handle_l1_putx(self, msg: Message, line: Optional[L2CacheLine]) -> None:
        """L1 evicting modified line."""
        baddr = msg.addr

        if line is None:
            # Stale putx - ignore
            return

        if line.state in (L2State.M, L2State.E, L2State.O, L2State.S):
            self.pending_wb[baddr] = msg.sender
            self.outgoing.append(Message(
                msg_type=MessageType.WB_ACK,
                addr=baddr,
                sender=self.bank_id,
                dest=msg.sender,
            ))

    def _handle_l1_puts(self, msg: Message, line: Optional[L2CacheLine]) -> None:
        """L1 evicting clean line."""
        if line is not None:
            line.sharers.discard(msg.sender)
            if line.owner == msg.sender:
                line.owner = -1

    def _handle_l1_wbdirtydata(self, msg: Message,
                                line: Optional[L2CacheLine]) -> None:
        """L1 sending dirty writeback data after receiving WB_ACK."""
        baddr = msg.addr

        if line is None:
            return

        if line.state in (L2State.M, L2State.E, L2State.O, L2State.S):
            # Normal writeback from L1
            line.data = msg.data
            line.dirty = True
            line.state = L2State.M
            line.sharers.discard(msg.sender)
            if baddr in self.pending_wb:
                del self.pending_wb[baddr]

    def handle_dir_response(self, msg: Message) -> None:
        """Handle response from directory controller."""
        baddr = msg.addr

        if msg.msg_type == MessageType.DIR_WB_ACK:
            # Look up in evicting_lines (lines removed from cache,
            # pending writeback acknowledgment)
            if baddr in self.evicting_lines:
                line = self.evicting_lines[baddr]
                # Clean up directory entry for evicted line
                self._remove_from_dir(line)
                line.state = L2State.I
                del self.evicting_lines[baddr]
            return

        # For non-WB_ACK messages, find the line in cache
        line = self._find_line(baddr)

        if line is None:
            # Check for any entry (including I state) in the set
            set_idx = self._get_set_index(baddr)
            for l in self.sets.get(set_idx, []):
                if l.addr == baddr:
                    line = l
                    break
            if line is None:
                return

        if msg.msg_type == MessageType.DIR_DATA_S:
            if line.state == L2State.ILS:
                line.data = msg.data
                line.state = L2State.S
                self._copy_dir_to_cache_and_remove(line)
                # Forward data to waiting L1s
                for sharer in line.sharers:
                    self.outgoing.append(Message(
                        msg_type=MessageType.DATA_S,
                        addr=baddr,
                        sender=self.bank_id,
                        dest=sharer,
                        data=msg.data,
                    ))

        elif msg.msg_type == MessageType.DIR_DATA_E:
            if line.state == L2State.ILX:
                line.data = msg.data
                line.state = L2State.M
                self._copy_dir_to_cache_and_remove(line)
                # Forward exclusive data to requesting L1
                if line.owner >= 0:
                    self.outgoing.append(Message(
                        msg_type=MessageType.DATA_E,
                        addr=baddr,
                        sender=self.bank_id,
                        dest=line.owner,
                        data=msg.data,
                    ))

    def drain_messages(self) -> List[Message]:
        msgs = self.outgoing[:]
        self.outgoing.clear()
        return msgs
