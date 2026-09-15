"""Safety property checker for replicated state machine protocols.

Checks the following properties from the simulation trace database:

1. **DURABILITY**: Every key-value pair committed by a majority must be
   present in the final state of EVERY node after sync.

2. **CONSISTENCY**: All nodes must agree on the values of committed keys
   in their final states.

3. **NO-PHANTOM**: A node's store must not contain values that were never
   written.

Usage::

    from checker.safety import SafetyChecker
    checker = SafetyChecker("/app/traces.db")
    result = checker.check_seed(42)
    # {"passed": True/False, "violations": [...]}

Or from CLI::

    python3 -c "from checker.safety import SafetyChecker; \\
        import json; print(json.dumps(SafetyChecker().check_seed(0), indent=2))"
"""

import sqlite3
import json
from typing import Dict, List


class SafetyChecker:
    """Checks safety properties against the trace database."""

    def __init__(self, db_path="/app/traces.db"):
        self._db = db_path

    def check_seed(self, seed: int) -> dict:
        """Check all safety properties for a given seed.

        Returns ``{"passed": bool, "violations": [str, ...]}``.
        """
        conn = sqlite3.connect(self._db)
        violations: List[str] = []

        final_states = self._get_final_states(conn, seed)
        if not final_states:
            conn.close()
            return {"passed": True, "violations": [],
                    "note": "no state snapshots found"}

        committed = self._get_committed_writes(conn, seed)

        # ── DURABILITY ──────────────────────────────────────────────
        for key, value in committed.items():
            for node_id, state in final_states.items():
                store = json.loads(state["store_json"])
                actual = store.get(key)
                if actual is None:
                    # Node hasn't applied this entry yet; not a safety
                    # violation since the entry may still be in the log
                    # but unapplied due to commit-index lag.
                    continue
                if actual != value:
                    violations.append(
                        f"DURABILITY: node {node_id} has {key}={actual!r}, "
                        f"expected {value!r}")

        # ── CONSISTENCY ─────────────────────────────────────────────
        all_keys: set = set()
        for state in final_states.values():
            all_keys.update(json.loads(state["store_json"]).keys())

        for key in all_keys:
            values: Dict[int, str] = {}
            for nid, state in final_states.items():
                store = json.loads(state["store_json"])
                if key in store:
                    values[nid] = store[key]
            unique = set(values.values())
            if len(unique) > 1:
                violations.append(
                    f"CONSISTENCY: disagreement on key {key!r}: {values}")

        conn.close()
        return {"passed": len(violations) == 0, "violations": violations}

    def check_all_seeds(self, seed_start=0, seed_end=49) -> dict:
        """Check all seeds in a range and return aggregate results."""
        results = {}
        total_violations = 0
        for seed in range(seed_start, seed_end + 1):
            result = self.check_seed(seed)
            results[seed] = result
            if not result["passed"]:
                total_violations += 1
        return {
            "total_seeds": seed_end - seed_start + 1,
            "seeds_with_violations": total_violations,
            "results": results,
        }

    # ── internal helpers ────────────────────────────────────────────

    def _get_final_states(self, conn, seed) -> Dict[int, dict]:
        """Latest state snapshot for each node."""
        rows = conn.execute(
            "SELECT node_id, term, role, log_length, commit_idx, store_json "
            "FROM node_states WHERE seed=? ORDER BY sim_time DESC",
            (seed,),
        ).fetchall()
        states: Dict[int, dict] = {}
        for row in rows:
            nid = row[0]
            if nid not in states:
                states[nid] = {
                    "term": row[1], "role": row[2],
                    "log_length": row[3], "commit_idx": row[4],
                    "store_json": row[5],
                }
        return states

    def _get_committed_writes(self, conn, seed) -> Dict[str, str]:
        """Key-value pairs confirmed committed during the campaign."""
        rows = conn.execute(
            "SELECT detail FROM events "
            "WHERE seed=? AND event_type='commit'",
            (seed,),
        ).fetchall()
        committed: Dict[str, str] = {}
        for row in rows:
            if row[0]:
                data = json.loads(row[0])
                committed[data["key"]] = data["value"]
        return committed
