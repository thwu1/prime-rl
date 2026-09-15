"""
MOESI Cache Coherence Simulator - Top-level coordinator

Connects L1 controllers, banked L2 cache, directory controllers,
and memory system. Drives simulation by processing messages
between components.
"""

from typing import List, Dict, Optional
from .types import MessageType, Message, block_addr, BLOCK_SIZE
from .l1_controller import L1Controller
from .l2_controller import L2Controller
from .cache_bank import BankedL2Cache
from .memory_system import MemorySystem


class CoherenceSimulator:
    """Top-level simulator coordinating all cache controllers."""

    def __init__(self, num_cores: int = 4, num_l2_banks: int = 4,
                 dual_memory: bool = False):
        self.num_cores = num_cores
        self.cycle = 0

        # Create L1 controllers (one per core)
        self.l1_controllers: List[L1Controller] = []
        for i in range(num_cores):
            self.l1_controllers.append(L1Controller(core_id=i))

        # Create banked L2 cache
        self.l2_cache = BankedL2Cache(num_banks=num_l2_banks)

        # Create memory system
        self.mem_system = MemorySystem(dual_memory=dual_memory)

        # Message queues
        self.l1_to_l2: List[Message] = []
        self.l2_to_l1: List[Message] = []
        self.l2_to_dir: List[Message] = []
        self.dir_to_l2: List[Message] = []

        # Simulation log
        self.log: List[str] = []
        self.max_cycles = 100000
        self.assertion_errors: List[str] = []

    def load(self, core_id: int, addr: int) -> Optional[bytes]:
        """Issue a load from a core."""
        hit, data = self.l1_controllers[core_id].load(addr)
        self._collect_l1_messages(core_id)
        return data if hit else None

    def store(self, core_id: int, addr: int, data: bytes) -> bool:
        """Issue a store from a core."""
        hit = self.l1_controllers[core_id].store(addr, data)
        self._collect_l1_messages(core_id)
        return hit

    def _collect_l1_messages(self, core_id: int) -> None:
        """Collect outgoing messages from an L1 controller."""
        msgs = self.l1_controllers[core_id].drain_messages()
        for msg in msgs:
            # Route to appropriate L2 bank
            bank_idx = self.l2_cache.get_bank_index(msg.addr)
            msg.dest = bank_idx
            self.l1_to_l2.append(msg)

    def step(self) -> bool:
        """
        Process one cycle of messages.
        Returns True if there are still pending messages.
        """
        self.cycle += 1
        had_work = False

        # Process L1 → L2 messages
        pending_l1_to_l2 = self.l1_to_l2[:]
        self.l1_to_l2.clear()
        for msg in pending_l1_to_l2:
            had_work = True
            bank = self.l2_cache.banks[msg.dest]
            try:
                bank.handle_l1_request(msg)
            except AssertionError as e:
                self.assertion_errors.append(
                    f"Cycle {self.cycle}: {str(e)}"
                )
                raise
            # Collect L2 responses
            for resp in bank.drain_messages():
                if resp.msg_type in (MessageType.DATA_S, MessageType.DATA_E,
                                     MessageType.INV, MessageType.WB_ACK):
                    self.l2_to_l1.append(resp)
                elif resp.msg_type in (MessageType.DIR_GETS, MessageType.DIR_GETX,
                                       MessageType.DIR_PUTX):
                    self.l2_to_dir.append(resp)

        # Process L2 → L1 messages
        pending_l2_to_l1 = self.l2_to_l1[:]
        self.l2_to_l1.clear()
        for msg in pending_l2_to_l1:
            had_work = True
            if msg.dest < len(self.l1_controllers):
                self.l1_controllers[msg.dest].handle_response(msg)
                self._collect_l1_messages(msg.dest)

        # Process L2 → Directory messages
        pending_l2_to_dir = self.l2_to_dir[:]
        self.l2_to_dir.clear()
        for msg in pending_l2_to_dir:
            had_work = True
            ctrl = self.mem_system.get_controller(msg.addr)
            ctrl.handle_request(msg)
            for resp in ctrl.drain_messages():
                self.dir_to_l2.append(resp)

        # Process Directory → L2 messages
        pending_dir_to_l2 = self.dir_to_l2[:]
        self.dir_to_l2.clear()
        for msg in pending_dir_to_l2:
            had_work = True
            bank = self.l2_cache.banks[msg.dest]
            try:
                bank.handle_dir_response(msg)
            except AssertionError as e:
                self.assertion_errors.append(
                    f"Cycle {self.cycle}: {str(e)}"
                )
                raise
            for resp in bank.drain_messages():
                if resp.msg_type in (MessageType.DATA_S, MessageType.DATA_E,
                                     MessageType.INV, MessageType.WB_ACK):
                    self.l2_to_l1.append(resp)
                elif resp.msg_type in (MessageType.DIR_GETS, MessageType.DIR_GETX,
                                       MessageType.DIR_PUTX):
                    self.l2_to_dir.append(resp)

        return had_work

    def run_until_idle(self, max_cycles: int = 10000) -> int:
        """Run simulation until no more pending messages."""
        cycles = 0
        while cycles < max_cycles:
            if not self.step():
                break
            cycles += 1
        return cycles

    def get_stats(self) -> dict:
        """Collect statistics from all controllers."""
        stats = {
            "cycles": self.cycle,
            "l1": [],
            "l2_banks": self.l2_cache.get_bank_distribution(),
            "memory": {
                "ranges": [(r.name, r.start, r.end) for r in self.mem_system.ranges],
                "overlaps": [(str(a), str(b)) for a, b in self.mem_system.check_ranges()],
            },
            "assertion_errors": self.assertion_errors[:],
        }
        for ctrl in self.l1_controllers:
            stats["l1"].append(ctrl.stats.copy())
        return stats
