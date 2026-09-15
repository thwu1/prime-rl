"""Consensus safety checker for strict serializability."""


class SafetyViolation(Exception):
    pass


class StateChecker:
    def __init__(self, replica_count: int):
        self.replica_count = replica_count
        self.commits = {
            0: {
                'checksum': 0,
                'parent_checksum': 0,
                'replicas': set(range(replica_count)),
            }
        }
        self.commit_mins = [0] * replica_count

    def on_commit(self, replica_index: int, op: int, checksum: int,
                  parent_checksum: int) -> None:
        assert 0 <= replica_index < self.replica_count
        assert op > 0

        current_min = self.commit_mins[replica_index]

        if op <= current_min:
            if op in self.commits and self.commits[op]['checksum'] != checksum:
                raise SafetyViolation(
                    f"Replica {replica_index} recommitted op {op} with "
                    f"divergent checksum: expected {self.commits[op]['checksum']}, "
                    f"got {checksum}"
                )
            return

        if op != current_min + 1:
            raise SafetyViolation(
                f"Replica {replica_index} skipped op: "
                f"expected {current_min + 1}, got {op}"
            )

        if current_min in self.commits:
            expected_parent = self.commits[current_min]['checksum']
            if parent_checksum != expected_parent:
                raise SafetyViolation(
                    f"Replica {replica_index} has wrong parent for op {op}: "
                    f"expected {expected_parent}, got {parent_checksum}"
                )

        if op in self.commits:
            if self.commits[op]['checksum'] != checksum:
                raise SafetyViolation(
                    f"Replica {replica_index} diverged at op {op}: "
                    f"existing {self.commits[op]['checksum']}, "
                    f"new {checksum}"
                )
            self.commits[op]['replicas'].add(replica_index)
        else:
            self.commits[op] = {
                'checksum': checksum,
                'parent_checksum': parent_checksum,
                'replicas': {replica_index},
            }

        self.commit_mins[replica_index] = op

    def check_convergence(self, replica_indices: set) -> bool:
        if not self.commits:
            return True
        max_op = max(self.commits.keys())
        return all(self.commit_mins[r] == max_op for r in replica_indices)

    def get_commit_count(self) -> int:
        return len(self.commits)

    def get_replica_commit_min(self, replica_index: int) -> int:
        return self.commit_mins[replica_index]
