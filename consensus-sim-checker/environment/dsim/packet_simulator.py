"""Deterministic network packet simulator with fault injection."""

import heapq
from dataclasses import dataclass


@dataclass
class PacketSimulatorOptions:
    node_count: int
    client_count: int = 0
    one_way_delay_mean: float = 50.0
    one_way_delay_min: float = 1.0
    packet_loss_probability: tuple = (0, 100)
    packet_replay_probability: tuple = (0, 100)
    partition_mode: str = "none"
    partition_symmetry: str = "symmetric"
    partition_probability: tuple = (0, 100)
    unpartition_probability: tuple = (0, 100)
    partition_stability: int = 0
    unpartition_stability: int = 0
    path_maximum_capacity: int = 20
    path_clog_duration_mean: float = 0.0
    path_clog_probability: tuple = (0, 100)


class PacketSimulator:
    def __init__(self, options: PacketSimulatorOptions, seed: int):
        from dsim.prng import DeterministicPRNG

        self.options = options
        self.prng = DeterministicPRNG(seed)
        self.ticks = 0
        self.process_count = options.node_count + options.client_count

        n = self.process_count
        self.link_queues = [[] for _ in range(n * n)]
        self.link_filters = [True] * (n * n)
        self.link_clogged_till = [0.0] * (n * n)

        self.partition_active = False
        self.partition = [False] * options.node_count
        self.partition_stability_remaining = options.unpartition_stability

        self._counter = 0

    def _path_index(self, source: int, target: int) -> int:
        return source * self.process_count + target

    def submit_packet(self, packet, source: int, target: int) -> None:
        idx = self._path_index(source, target)
        queue = self.link_queues[idx]

        if len(queue) >= self.options.path_maximum_capacity:
            drop_idx = self.prng.range_inclusive(0, len(queue) - 1)
            queue.pop(drop_idx)
            heapq.heapify(queue)

        delay = max(
            self.options.one_way_delay_min,
            self.prng.exponential(self.options.one_way_delay_mean),
        )
        ready_at = self.ticks + delay
        self._counter += 1
        heapq.heappush(queue, (ready_at, self._counter, packet, source, target))

    def tick(self) -> None:
        self.ticks += 1

        if self.partition_stability_remaining > 0:
            self.partition_stability_remaining -= 1
        else:
            if self.partition_active:
                if self.prng.chance(*self.options.unpartition_probability):
                    self.partition_active = False
                    self.partition_stability_remaining = self.options.unpartition_stability
                    self.partition = [False] * self.options.node_count
                    self.link_filters = [True] * (self.process_count * self.process_count)
            else:
                if (self.options.node_count > 1
                        and self.prng.chance(*self.options.partition_probability)):
                    self._auto_partition_network()

        for source in range(self.process_count):
            for target in range(self.process_count):
                if self.prng.chance(*self.options.path_clog_probability):
                    idx = self._path_index(source, target)
                    duration = self.prng.exponential(self.options.path_clog_duration_mean)
                    self.link_clogged_till[idx] = self.ticks + duration

    def step(self) -> list:
        delivered = []
        for source in range(self.process_count):
            for target in range(self.process_count):
                idx = self._path_index(source, target)

                if self.link_clogged_till[idx] > self.ticks:
                    continue

                queue = self.link_queues[idx]
                if queue and queue[0][0] <= self.ticks:
                    _, _, packet, src, tgt = heapq.heappop(queue)

                    if not self.link_filters[idx]:
                        continue

                    if self.prng.chance(*self.options.packet_loss_probability):
                        continue

                    if self.prng.chance(*self.options.packet_replay_probability):
                        self.submit_packet(packet, source, target)

                    delivered.append((packet, source, target))

        return delivered

    def _auto_partition_network(self) -> None:
        mode = self.options.partition_mode
        n = self.options.node_count

        if mode == "none":
            return

        partition = [False] * n

        if mode == "uniform_size":
            partition_size = self.prng.range_inclusive(0, n - 1)
            nodes = self.prng.shuffle(list(range(n)))
            for i in range(partition_size):
                partition[nodes[i]] = True

        elif mode == "uniform_partition":
            partition[0] = self.prng.boolean()
            only_same = True
            for i in range(1, n):
                partition[i] = self.prng.boolean()
                only_same = only_same and (partition[i - 1] == partition[i])
            if only_same:
                idx = self.prng.range_inclusive(0, n - 1)
                partition[idx] = True

        elif mode == "isolate_single":
            idx = self.prng.range_inclusive(0, n - 1)
            partition[idx] = True

        self.partition = partition
        self.partition_active = True
        self.partition_stability_remaining = self.options.partition_stability

        asymmetric_side = self.prng.boolean()
        for src in range(self.process_count):
            for tgt in range(self.process_count):
                link_idx = self._path_index(src, tgt)
                if src >= n or tgt >= n:
                    self.link_filters[link_idx] = True
                elif partition[src] == partition[tgt]:
                    self.link_filters[link_idx] = True
                elif (self.options.partition_symmetry == "asymmetric"
                      and partition[src] == asymmetric_side):
                    self.link_filters[link_idx] = True
                else:
                    self.link_filters[link_idx] = False

    def get_partition(self) -> list:
        return list(self.partition)

    def is_partitioned(self) -> bool:
        return self.partition_active
