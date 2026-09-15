// Extracted from TigerBeetle src/vsr.zig — Flexible Paxos quorum calculation
// https://github.com/tigerbeetle/tigerbeetle
//
// constants.quorum_replication_max is typically 3.
// stdx.div_ceil(a, b) computes ceiling division: (a + b - 1) / b.

pub fn quorums(replica_count: u8) struct {
    replication: u8,
    view_change: u8,
    nack_prepare: u8,
    majority: u8,
    upgrade: u8,
} {
    assert(replica_count > 0);

    assert(constants.quorum_replication_max >= 2);
    // For replica_count=2, set quorum_replication=2 even though =1 would intersect.
    // This improves durability of small clusters.
    const quorum_replication = if (replica_count == 2) 2 else @min(
        constants.quorum_replication_max,
        stdx.div_ceil(replica_count, 2),
    );
    assert(quorum_replication <= replica_count);
    assert(quorum_replication >= 2 or quorum_replication == replica_count);

    // For replica_count=2, set quorum_view_change=2 even though =1 would intersect.
    // This avoids special cases for a single-replica view-change in Replica.
    const quorum_view_change =
        if (replica_count == 2) 2 else replica_count - quorum_replication + 1;
    // The view change quorum may be more expensive to make the replication quorum cheaper.
    // The insight is that the replication phase is by far more common than the view change.
    assert(quorum_view_change <= replica_count);
    assert(quorum_view_change >= 2 or quorum_view_change == replica_count);
    assert(quorum_view_change >= @divFloor(replica_count, 2) + 1);
    assert(quorum_view_change + quorum_replication > replica_count);

    // We need enough nacks to guarantee that quorum_replication was not reached,
    // because if the replication quorum was reached, then it may have been committed.
    const quorum_nack_prepare = replica_count - quorum_replication + 1;
    assert(quorum_nack_prepare + quorum_replication > replica_count);

    const quorum_majority =
        stdx.div_ceil(replica_count, 2) + @intFromBool(@mod(replica_count, 2) == 0);
    assert(quorum_majority <= replica_count);
    assert(quorum_majority > @divFloor(replica_count, 2));

    // Require all replicas to upgrade.
    const quorum_upgrade = replica_count;
    assert(quorum_upgrade <= replica_count);
    assert(quorum_upgrade >= quorum_replication);
    assert(quorum_upgrade >= quorum_view_change);

    return .{
        .replication = quorum_replication,
        .view_change = quorum_view_change,
        .nack_prepare = quorum_nack_prepare,
        .majority = quorum_majority,
        .upgrade = quorum_upgrade,
    };
}

test "quorums" {
    if (constants.quorum_replication_max != 3) return error.SkipZigTest;

    const expect_replication = [_]u8{ 1, 2, 2, 2, 3, 3, 3, 3 };
    const expect_view_change = [_]u8{ 1, 2, 2, 3, 3, 4, 5, 6 };
    const expect_nack_prepare = [_]u8{ 1, 1, 2, 3, 3, 4, 5, 6 };
    const expect_majority = [_]u8{ 1, 2, 2, 3, 3, 4, 4, 5 };
}
