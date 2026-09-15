// Extracted from TigerBeetle src/testing/packet_simulator.zig
// https://github.com/tigerbeetle/tigerbeetle
//
// Key functions: auto_partition_network, submit_packet, step
//
// Note: prng.range_inclusive(T, lo, hi) returns a random value in [lo, hi] inclusive.
// prng.index(slice) returns a random valid index into the slice.
// prng.shuffle(T, slice) performs an in-place Fisher-Yates shuffle.

/// Determines how the partitions are created.
/// Only nodes (replicas or standbys) are partitioned.
/// There will always be exactly two partitions.
pub const PartitionMode = enum {
    /// Disable automatic partitioning.
    none,

    /// Draws the size of the partition uniformly at random from (1, n-1).
    /// Replicas are randomly assigned a partition.
    uniform_size,

    /// Assigns each node to a partition uniformly at random. This biases towards
    /// equal-size partitions.
    uniform_partition,

    /// Isolates exactly one node.
    isolate_single,
};

/// Partitions the network. Guaranteed to isolate at least one replica.
fn auto_partition_network(self: *PacketSimulator) void {
    assert(self.options.node_count > 1);

    var partition = self.auto_partition;
    switch (self.options.partition_mode) {
        .none => @memset(partition, false),
        .uniform_size => {
            const partition_size =
                self.prng.range_inclusive(u8, 1, self.options.node_count - 1);
            self.prng.shuffle(u8, self.auto_partition_nodes);
            for (self.auto_partition_nodes, 0..) |r, i| {
                partition[r] = i < partition_size;
            }
        },
        .uniform_partition => {
            var only_same = true;
            partition[0] = self.prng.boolean();

            var i: usize = 1;
            while (i < self.options.node_count) : (i += 1) {
                partition[i] = self.prng.boolean();
                only_same =
                    only_same and (partition[i - 1] == partition[i]);
            }

            if (only_same) {
                const n = self.prng.index(partition);
                partition[n] = true;
            }
        },
        .isolate_single => {
            @memset(partition, false);
            const n = self.prng.index(partition);
            partition[n] = true;
        },
    }

    self.auto_partition_active = true;
    self.auto_partition_stability = self.options.partition_stability;

    const asymmetric_partition_side = self.prng.boolean();
    var from: u8 = 0;
    while (from < self.process_count()) : (from += 1) {
        var to: u8 = 0;
        while (to < self.process_count()) : (to += 1) {
            const path: Path = .{ .source = from, .target = to };
            const enabled =
                from >= self.options.node_count or
                to >= self.options.node_count or
                partition[from] == partition[to] or
                (self.options.partition_symmetry == .asymmetric and
                    partition[from] == asymmetric_partition_side);
            self.links[self.path_index(path)].filter =
                if (enabled) LinkFilter.initFull() else LinkFilter{};
        }
    }
}

pub fn submit_packet(
    self: *PacketSimulator,
    packet: Packet,
    path: Path,
) void {
    const queue = &self.links[self.path_index(path)].queue;
    const queue_count = queue.count();
    if (queue_count + 1 > self.options.path_maximum_capacity) {
        // Drop a random existing packet to make room
        const link_packet = queue.removeIndex(self.prng.index(queue.items));
        defer self.packet_deinit(link_packet.packet);
    }

    queue.add(.{
        .ready_at = self.tick_instant().add(self.packet_delay(packet, path)),
        .packet = packet,
    }) catch unreachable;
}

pub fn step(self: *PacketSimulator) bool {
    var advanced = false;
    for (0..self.process_count()) |from| {
        for (0..self.process_count()) |to| {
            const path: Path = .{ .source = @intCast(from), .target = @intCast(to) };
            if (self.is_clogged(path)) continue;

            const queue = &self.links[self.path_index(path)].queue;
            if (queue.peek()) |link_packet| {
                if (link_packet.ready_at.ns <= self.tick_instant().ns) {
                    _ = queue.remove();
                    self.submit_packet_finish(path, link_packet);
                    self.packet_deinit(link_packet.packet);
                    advanced = true;
                }
            }
        }
    }
    return advanced;
}
