"""Liveness mode: core selection and repair deadlock (resonance bug) detection."""


def select_random_core(prng, replica_count: int, standby_count: int,
                       view_change_quorum: int) -> set:
    assert replica_count > 0
    assert view_change_quorum <= replica_count

    replica_core_count = prng.range_inclusive(view_change_quorum, replica_count)
    indices = prng.shuffle(list(range(replica_count)))
    core = set(indices[:replica_core_count])

    if standby_count > 0:
        standby_core_count = prng.range_inclusive(0, standby_count)
        standby_indices = prng.shuffle(
            list(range(replica_count, replica_count + standby_count))
        )
        core.update(standby_indices[:standby_core_count])

    return core


def detect_repair_deadlock(available_ops: dict, all_ops: set) -> list:
    """Detect the resonance bug pattern in round-robin repair.

    A replica is 'stuck' if there exists any round-robin counter value where
    it cannot repair all its missing ops, because each repair request is
    directed to a replica that lacks the needed op.

    Args:
        available_ops: {replica_index: set of ops this replica has}
        all_ops: set of all ops every replica should have

    Returns:
        List of replica indices that can be deadlocked.
    """
    replica_indices = sorted(available_ops.keys())
    n = len(replica_indices)
    stuck = []

    for replica_idx in replica_indices:
        missing = sorted(all_ops - available_ops[replica_idx])
        if not missing:
            continue

        has_deadlock_counter = False
        for counter in range(n):
            can_repair_all = True
            for i, op in enumerate(missing):
                target_pos = (counter + i) % n
                target = replica_indices[target_pos]
                if target == replica_idx:
                    target_pos = (target_pos + 1) % n
                    target = replica_indices[target_pos]
                if op not in available_ops.get(target, set()):
                    can_repair_all = False
                    break
            if not can_repair_all:
                has_deadlock_counter = True
                break

        if has_deadlock_counter:
            stuck.append(replica_idx)

    return stuck
