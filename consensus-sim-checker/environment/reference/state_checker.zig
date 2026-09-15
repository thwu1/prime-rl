// Extracted from TigerBeetle src/testing/cluster/state_checker.zig
// https://github.com/tigerbeetle/tigerbeetle
//
// The state checker validates strict serializability by maintaining a canonical
// commit history and comparing each replica's state against it.
//
// Key data structures:
//   commits: ArrayList — canonical commit history (one entry per committed op)
//   commit_mins: [members_max]u64 — latest op committed by each replica
//
// Key invariant enforced in check_state():

pub fn check_state(state_checker: *StateChecker, replica_index: u8) !void {
    // ... (sync handling omitted) ...

    const commit_a = state_checker.commit_mins[replica_index];
    const commit_b = replica.commit_min;

    const checksum_a = state_checker.commits.items[commit_a].header.checksum;
    const checksum_b = /* replica's current checksum for commit_b */;

    // CRITICAL INVARIANT: if the op numbers match, checksums MUST match.
    // This detects divergent state even when a replica "recommits" the same op
    // (e.g. after a restart/replay). A replica that reports the same op number
    // but a different checksum indicates a consensus safety violation.
    assert((commit_a == commit_b) == (checksum_a == checksum_b));

    if (checksum_a == checksum_b) return;

    // Replica has advanced: commit_b should be exactly commit_a + 1
    assert(commit_b < commit_a or commit_a + 1 == commit_b);
    state_checker.commit_mins[replica_index] = commit_b;

    // Verify the new commit matches canonical history
    if (replica.commit_min < state_checker.commits.items.len) {
        const commit = &state_checker.commits.items[commit_b];
        assert(checksum_b == commit.header.checksum);
        commit.replicas.set(replica_index);
        return;
    }

    // New commit extends canonical history
    assert(header_b.?.parent == checksum_a);
    assert(header_b.?.op > 0);
    // ... (append to commits) ...
}
