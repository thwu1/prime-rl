#!/usr/bin/env python3
"""
Totally-available, read-committed transactional KV store for Maelstrom txn-rw-register.

Architecture:
  - Single-threaded sequential message processing on each node (prevents G1b:
    no intermediate reads since writes commit atomically between message
    processing steps).
  - Lamport timestamps (seq, node_id) for deterministic last-writer-wins
    conflict resolution across nodes (prevents G0: global total order on
    writes means no write-write dependency cycles).
  - Full-state snapshot replication after each write transaction (prevents
    G1c: if peer P sees transaction T's writes, P also receives all writes
    that T's node had committed before T, preserving causal consistency).
  - Fire-and-forget replication (total availability: responses never blocked
    on inter-node communication, even during network partitions).
  - Lamport clock advancement on replication receipt ensures future local
    writes always have timestamps strictly greater than any received value,
    so local writes are never silently rolled back by stale replications.
  - G1a (aborted reads) trivially prevented: we never abort transactions.
"""
import sys
import json


def main():
    node_id = None
    node_ids = []
    # Local key-value state: maps integer keys to integer values
    state = {}
    # Lamport timestamps for each key: maps key -> (seq, node_id_str)
    # Used for deterministic conflict resolution during replication merges
    timestamps = {}
    # Monotonic Lamport clock — advanced on local commits AND on receiving
    # replications, ensuring new local writes always dominate old replicated
    # values
    seq = 0
    # Outgoing message counter for unique msg_ids
    msg_counter = 0

    def send(dest, body):
        nonlocal msg_counter
        msg_counter += 1
        body["msg_id"] = msg_counter
        line = json.dumps({"src": node_id, "dest": dest, "body": body})
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def reply(request, body):
        body["in_reply_to"] = request["body"]["msg_id"]
        send(request["src"], body)

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        msg = json.loads(raw_line)
        body = msg["body"]
        msg_type = body["type"]

        # ----- INIT -----
        if msg_type == "init":
            node_id = body["node_id"]
            node_ids = body["node_ids"]
            reply(msg, {"type": "init_ok"})
            sys.stderr.write(f"Node {node_id} initialized, cluster: {node_ids}\n")
            sys.stderr.flush()

        # ----- TXN (client transaction) -----
        elif msg_type == "txn":
            seq += 1
            ts = (seq, node_id)

            txn_ops = body["txn"]
            result = []
            # Buffer writes within this transaction for atomic commit
            pending_writes = {}

            for op in txn_ops:
                fn = op[0]
                key = op[1]
                if fn == "r":
                    # Read-your-writes: check pending writes first, then
                    # committed state
                    val = pending_writes.get(key, state.get(key))
                    result.append(["r", key, val])
                elif fn == "w":
                    val = op[2]
                    pending_writes[key] = val
                    result.append(["w", key, val])

            # Atomic commit: apply all buffered writes with this transaction's
            # Lamport timestamp
            for k, v in pending_writes.items():
                state[k] = v
                timestamps[k] = ts

            # Respond to the client immediately (total availability)
            reply(msg, {"type": "txn_ok", "txn": result})

            # Replicate the FULL state snapshot to all peers.
            # Sending the complete state (not just this transaction's writes)
            # is critical for causal consistency: if a peer receives this
            # message, it learns about ALL writes this node had committed up
            # to this point, including writes from other peers that were
            # previously replicated to us. This prevents G1c by ensuring a
            # peer cannot observe a "later" transaction's effect without also
            # observing the effects of all "earlier" transactions on this node.
            if pending_writes:
                snapshot = [
                    [k, v, timestamps[k][0], timestamps[k][1]]
                    for k, v in state.items()
                ]
                for nid in node_ids:
                    if nid != node_id:
                        send(nid, {"type": "replicate", "state": snapshot})

        # ----- REPLICATE (peer state sync) -----
        elif msg_type == "replicate":
            received = body.get("state", [])
            if received:
                # Advance Lamport clock past the highest seq in the received
                # snapshot. This guarantees that any future local write will
                # have a strictly higher timestamp than any value in the
                # received state, preventing the scenario where a new local
                # write gets a lower timestamp than a replicated value and is
                # later "rolled back" by another replication carrying that
                # same old value.
                max_remote_seq = max(entry[2] for entry in received)
                seq = max(seq, max_remote_seq)

                # Merge: for each key, keep whichever version has the higher
                # Lamport timestamp. Tuple comparison (seq, node_id_str) is
                # deterministic across all nodes, ensuring convergence.
                for entry in received:
                    key = entry[0]
                    val = entry[1]
                    remote_ts = (entry[2], entry[3])
                    local_ts = timestamps.get(key, (0, ""))
                    if remote_ts > local_ts:
                        state[key] = val
                        timestamps[key] = remote_ts


if __name__ == "__main__":
    main()
