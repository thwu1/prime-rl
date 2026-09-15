"""
Directory Controller - MOESI_CMP_Directory Protocol

Central directory that tracks which L2 banks hold copies of each
cache line. Handles coherence at the L2-to-memory level.
"""

from typing import Dict, List, Optional
from .types import (
    DirState, DirEntry, MessageType, Message, block_addr,
)


class DirectoryController:
    """Directory-based coherence controller for L2 banks."""

    def __init__(self, mem_start: int, mem_size: int, ctrl_id: int = 0):
        self.ctrl_id = ctrl_id
        self.mem_start = mem_start
        self.mem_size = mem_size
        self.mem_end = mem_start + mem_size

        # Directory entries: block_addr -> DirEntry
        self.entries: Dict[int, DirEntry] = {}

        # Backing memory storage
        self.memory: Dict[int, bytes] = {}

        self.outgoing: List[Message] = []

        self.stats = {
            "gets_requests": 0,
            "getx_requests": 0,
            "putx_requests": 0,
        }

    def _get_or_create_entry(self, addr: int) -> DirEntry:
        baddr = block_addr(addr)
        if baddr not in self.entries:
            self.entries[baddr] = DirEntry(addr=baddr, state=DirState.I)
        return self.entries[baddr]

    def in_range(self, addr: int) -> bool:
        """Check if address is in this controller's range."""
        return self.mem_start <= addr < self.mem_end

    def handle_request(self, msg: Message) -> None:
        """Handle request from L2 controller."""
        baddr = msg.addr
        entry = self._get_or_create_entry(baddr)

        if msg.msg_type == MessageType.DIR_GETS:
            self._handle_gets(msg, entry)
        elif msg.msg_type == MessageType.DIR_GETX:
            self._handle_getx(msg, entry)
        elif msg.msg_type == MessageType.DIR_PUTX:
            self._handle_putx(msg, entry)

    def _handle_gets(self, msg: Message, entry: DirEntry) -> None:
        """L2 requesting shared copy."""
        self.stats["gets_requests"] += 1

        if entry.state == DirState.I:
            # Not cached anywhere - provide from memory
            data = self.memory.get(entry.addr, b'\x00' * 64)
            entry.state = DirState.S
            entry.sharers.add(msg.sender)
            self.outgoing.append(Message(
                msg_type=MessageType.DIR_DATA_S,
                addr=entry.addr,
                sender=self.ctrl_id,
                dest=msg.sender,
                data=data,
            ))
        elif entry.state == DirState.S:
            data = self.memory.get(entry.addr, b'\x00' * 64)
            entry.sharers.add(msg.sender)
            self.outgoing.append(Message(
                msg_type=MessageType.DIR_DATA_S,
                addr=entry.addr,
                sender=self.ctrl_id,
                dest=msg.sender,
                data=data,
            ))
        elif entry.state == DirState.M:
            # Must recall from owner first, simplified: provide from memory
            data = self.memory.get(entry.addr, b'\x00' * 64)
            entry.state = DirState.S
            entry.sharers.add(msg.sender)
            entry.sharers.add(entry.owner)
            entry.owner = -1
            self.outgoing.append(Message(
                msg_type=MessageType.DIR_DATA_S,
                addr=entry.addr,
                sender=self.ctrl_id,
                dest=msg.sender,
                data=data,
            ))

    def _handle_getx(self, msg: Message, entry: DirEntry) -> None:
        """L2 requesting exclusive copy."""
        self.stats["getx_requests"] += 1

        data = self.memory.get(entry.addr, b'\x00' * 64)

        if entry.state == DirState.I:
            entry.state = DirState.M
            entry.owner = msg.sender
            self.outgoing.append(Message(
                msg_type=MessageType.DIR_DATA_E,
                addr=entry.addr,
                sender=self.ctrl_id,
                dest=msg.sender,
                data=data,
            ))
        elif entry.state == DirState.S:
            entry.state = DirState.M
            entry.sharers.clear()
            entry.owner = msg.sender
            self.outgoing.append(Message(
                msg_type=MessageType.DIR_DATA_E,
                addr=entry.addr,
                sender=self.ctrl_id,
                dest=msg.sender,
                data=data,
            ))
        elif entry.state == DirState.M:
            entry.owner = msg.sender
            self.outgoing.append(Message(
                msg_type=MessageType.DIR_DATA_E,
                addr=entry.addr,
                sender=self.ctrl_id,
                dest=msg.sender,
                data=data,
            ))

    def _handle_putx(self, msg: Message, entry: DirEntry) -> None:
        """L2 writing back modified line."""
        self.stats["putx_requests"] += 1

        if msg.data is not None:
            self.memory[entry.addr] = msg.data

        if entry.state == DirState.M:
            entry.state = DirState.MI
            # Send writeback ack
            self.outgoing.append(Message(
                msg_type=MessageType.DIR_WB_ACK,
                addr=entry.addr,
                sender=self.ctrl_id,
                dest=msg.sender,
            ))
            entry.state = DirState.I
            entry.owner = -1
            entry.sharers.clear()
        elif entry.state == DirState.I:
            # Already invalid - just ack
            self.outgoing.append(Message(
                msg_type=MessageType.DIR_WB_ACK,
                addr=entry.addr,
                sender=self.ctrl_id,
                dest=msg.sender,
            ))

    def drain_messages(self) -> List[Message]:
        msgs = self.outgoing[:]
        self.outgoing.clear()
        return msgs
