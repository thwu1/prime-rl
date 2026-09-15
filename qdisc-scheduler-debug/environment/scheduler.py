"""
CAKE-inspired packet scheduler simulator.

This simulator models a simplified version of the Linux CAKE qdisc (Common
Applications Kept Enhanced). It processes a packet trace through a scheduling
pipeline consisting of:

  1. Per-flow queuing via hash-based flow isolation
  2. Deficit Round Robin (DRR) for fair bandwidth allocation across flows
  3. Rate-limited output link for bandwidth enforcement

The simulator reads a CSV packet trace, processes it through the scheduler,
and outputs the scheduled packet sequence with dequeue timestamps.

Inspired by: "mq-cake: Scaling Software Rate Limiting Across CPU Cores"
(NetDev 0x19, Zagreb 2025) and the CAKE qdisc in the Linux kernel.
"""


import csv
import json
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Packet:
    """Represents a network packet with arrival metadata."""
    arrival_ns: int      # Arrival timestamp in nanoseconds
    flow_id: int         # Flow identifier (e.g., 5-tuple hash)
    size_bytes: int      # Packet size in bytes (including headers)


@dataclass
class FlowQueue:
    """Per-flow FIFO queue with DRR deficit counter."""
    qid: int
    flow_id: int = -1
    deficit: int = 0
    pkts: List[Packet] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return len(self.pkts) == 0

    @property
    def head(self) -> Optional[Packet]:
        return self.pkts[0] if self.pkts else None

    def enqueue(self, pkt: Packet):
        self.pkts.append(pkt)

    def dequeue(self) -> Packet:
        return self.pkts.pop(0)


class FlowHashTable:
    """
    Hash table for mapping flows to per-flow queues.

    Uses a simple modular hash to distribute flows across queues.
    In the real CAKE qdisc, this uses set-associative hashing (like a
    CPU cache) with 8-way associativity to limit collision impacts.
    Here we use direct-mapped hashing for simplicity.
    """

    def __init__(self, num_queues: int):
        self.num_queues = num_queues
        self.queues = [FlowQueue(qid=i) for i in range(num_queues)]

    def lookup(self, flow_id: int) -> FlowQueue:
        """Map a flow ID to its designated queue."""
        qid = flow_id % (self.num_queues - 1)
        q = self.queues[qid]
        q.flow_id = flow_id
        return q

    def get_queue(self, qid: int) -> FlowQueue:
        return self.queues[qid]


class DRRScheduler:
    """
    Deficit Round Robin (DRR) fair queuing scheduler.

    DRR allocates bandwidth fairly among active queues by tracking a
    'deficit counter' per queue. Each round, queues receive a 'quantum'
    of additional credit. Queues can transmit packets as long as their
    deficit counter covers the packet size.

    Reference: M. Shreedhar and G. Varghese, "Efficient Fair Queuing
    Using Deficit Round-Robin," IEEE/ACM Trans. Networking, 1996.
    """

    def __init__(self, quantum: int):
        self.quantum = quantum
        self.active: List[FlowQueue] = []

    def activate(self, queue: FlowQueue):
        """Add a queue to the active set if not already present."""
        if queue not in self.active:
            self.active.append(queue)

    @property
    def has_active(self) -> bool:
        return len(self.active) > 0

    def schedule_round(self, transmit_fn) -> bool:
        """
        Execute one DRR round across active queues.

        Iterates over active queues in round-robin order. For each queue,
        dequeues packets while the deficit counter covers the head packet.
        Empty queues are removed from the active set; non-empty queues
        are rotated to the back.

        Args:
            transmit_fn: Callable(Packet, FlowQueue) for each dequeued packet.

        Returns:
            True if any packet was dequeued.
        """
        if not self.active:
            return False

        made_progress = False
        n = len(self.active)

        for _ in range(n):
            if not self.active:
                break

            q = self.active[0]

            # Skip empty queues
            if q.empty:
                self.active.pop(0)
                q.deficit = 0
                continue

            # Drain packets while deficit permits
            while not q.empty and q.deficit >= q.head.size_bytes:
                pkt = q.dequeue()
                q.deficit -= pkt.size_bytes
                transmit_fn(pkt, q)
                made_progress = True

            # Manage active list
            if q.empty:
                self.active.pop(0)
                q.deficit = 0
            else:
                # Rotate to back of round-robin
                self.active.pop(0)
                self.active.append(q)

        return made_progress


class CAKESimulator:
    """
    Main scheduler combining flow hashing, DRR, and rate limiting.

    Simulates packet processing through a CAKE-like scheduler pipeline:

      Packet arrival -> Flow hash -> Per-flow queue -> DRR selection ->
      Rate-limited link -> Output

    The rate-limited link model uses a simple transmission time calculation:
    each packet occupies the link for (size_bits / rate_bps) seconds.
    """

    def __init__(self, config: dict):
        rate_mbps = config['rate_mbps']
        self.rate_bps = rate_mbps * 1_000_000  # Convert Mbps to bits/sec

        num_queues = config.get('num_queues', 64)
        self.flow_table = FlowHashTable(num_queues)

        quantum = config.get('quantum', 1500)
        self.drr = DRRScheduler(quantum)

        self.link_free_ns = 0   # Earliest time the output link is free
        self.results: List[dict] = []

    def _enqueue(self, pkt: Packet):
        """Assign packet to its flow queue and activate in DRR."""
        q = self.flow_table.lookup(pkt.flow_id)
        q.enqueue(pkt)
        self.drr.activate(q)

    def _transmit(self, pkt: Packet, q: FlowQueue):
        """Transmit a packet on the rate-limited output link."""
        # Calculate transmission time based on link rate
        # Transmission time = packet_size_in_bits / link_rate_in_bps
        tx_ns = int(pkt.size_bytes * 1_000_000_000 / self.rate_bps)

        # Packet cannot leave before it arrived or before link is free
        dequeue_ns = max(self.link_free_ns, pkt.arrival_ns) + tx_ns
        self.link_free_ns = dequeue_ns

        self.results.append({
            'dequeue_ns': dequeue_ns,
            'flow_id': pkt.flow_id,
            'size_bytes': pkt.size_bytes,
            'queue_id': q.qid,
        })

    def run(self, packets: List[Packet]) -> List[dict]:
        """
        Process a list of packets through the scheduler.

        Phase 1: Enqueue all packets into per-flow queues.
        Phase 2: Drain queues using DRR with rate-limited output.

        Returns list of output records with dequeue timestamps.
        """
        # Phase 1: Enqueue all packets (sorted by arrival time)
        sorted_pkts = sorted(packets, key=lambda p: p.arrival_ns)
        for pkt in sorted_pkts:
            self._enqueue(pkt)

        total_enqueued = sum(
            len(q.pkts) for q in self.flow_table.queues
        )
        print(f"Enqueued {total_enqueued} packets into "
              f"{sum(1 for q in self.flow_table.queues if not q.empty)} "
              f"active queues", file=sys.stderr)

        # Phase 2: DRR drain with rate limiting
        rounds = 0
        max_rounds = total_enqueued * 2  # Safety limit
        while self.drr.has_active and rounds < max_rounds:
            if not self.drr.schedule_round(self._transmit):
                print(f"WARNING: DRR stalled after {len(self.results)} "
                      f"packets (round {rounds})", file=sys.stderr)
                break
            rounds += 1

        if self.drr.has_active:
            remaining = sum(
                len(q.pkts) for q in self.flow_table.queues
            )
            print(f"WARNING: {remaining} packets remain in queues "
                  f"after {rounds} rounds", file=sys.stderr)

        return self.results


def load_trace(path: str) -> List[Packet]:
    """Load packets from CSV trace file."""
    packets = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            packets.append(Packet(
                arrival_ns=int(row['timestamp_ns']),
                flow_id=int(row['flow_id']),
                size_bytes=int(row['size_bytes']),
            ))
    return packets


def save_output(results: List[dict], path: str):
    """Write scheduler output to CSV."""
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['dequeue_ns', 'flow_id', 'size_bytes', 'queue_id'],
        )
        writer.writeheader()
        for r in results:
            writer.writerow(r)
