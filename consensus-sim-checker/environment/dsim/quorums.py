"""Flexible Paxos quorum calculator."""


def compute_quorums(replica_count: int, quorum_replication_max: int = 3) -> dict:
    assert replica_count > 0

    quorum_replication = min(quorum_replication_max, max(1, replica_count // 2))

    quorum_view_change = replica_count - quorum_replication + 1

    quorum_nack_prepare = replica_count - quorum_replication + 1

    quorum_majority = replica_count // 2 + 1

    quorum_upgrade = replica_count

    return {
        'replication': quorum_replication,
        'view_change': quorum_view_change,
        'nack_prepare': quorum_nack_prepare,
        'majority': quorum_majority,
        'upgrade': quorum_upgrade,
    }
