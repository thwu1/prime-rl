"""Flexible Paxos quorum calculator."""

import math


def compute_quorums(replica_count: int, quorum_replication_max: int = 3) -> dict:
    assert replica_count > 0
    assert quorum_replication_max >= 2

    # Replication quorum
    if replica_count == 2:
        quorum_replication = 2
    else:
        quorum_replication = min(quorum_replication_max, math.ceil(replica_count / 2))

    assert quorum_replication <= replica_count
    assert quorum_replication >= 2 or quorum_replication == replica_count

    # View-change quorum
    if replica_count == 2:
        quorum_view_change = 2
    else:
        quorum_view_change = replica_count - quorum_replication + 1

    assert quorum_view_change <= replica_count
    assert quorum_view_change >= 2 or quorum_view_change == replica_count
    assert quorum_view_change >= replica_count // 2 + 1
    assert quorum_view_change + quorum_replication > replica_count

    # Nack quorum
    quorum_nack_prepare = replica_count - quorum_replication + 1
    assert quorum_nack_prepare + quorum_replication > replica_count

    # Majority
    quorum_majority = replica_count // 2 + 1
    assert quorum_majority <= replica_count
    assert quorum_majority > replica_count // 2

    # Upgrade
    quorum_upgrade = replica_count

    return {
        'replication': quorum_replication,
        'view_change': quorum_view_change,
        'nack_prepare': quorum_nack_prepare,
        'majority': quorum_majority,
        'upgrade': quorum_upgrade,
    }
