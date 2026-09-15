#!/usr/bin/env python3
"""
Generate transaction data for a 3-shard MVCC key-value store and load into PostgreSQL.
Deterministic (seeded) with known consistency anomalies injected.
"""

import random
import subprocess
import os
import sys

SEED = 314159
NUM_SHARDS = 3
KEYS_PER_SHARD = 50

random.seed(SEED)


class HLC:
    """Hybrid Logical Clock."""
    def __init__(self, physical=1000):
        self.physical = physical
        self.logical = 0

    def tick(self):
        if random.random() < 0.2:
            self.logical += 1
        else:
            self.physical += random.randint(1, 5)
            self.logical = 0
        return (self.physical, self.logical)


class IdGen:
    def __init__(self):
        self._single = 0
        self._cross = 0

    def single(self):
        self._single += 1
        return f"T_{self._single:04d}"

    def cross(self):
        self._cross += 1
        return f"X_{self._cross:04d}"


class Generator:
    def __init__(self):
        self.clocks = [HLC(1000 + i * 1000) for i in range(NUM_SHARDS)]
        self.ids = IdGen()
        self.operations = []
        self.tx_outcomes = []
        self.op_seqs = {}
        self.kv = {}
        for s in range(NUM_SHARDS):
            for k in range(KEYS_PER_SHARD):
                self.kv[(s, f"s{s}_k{k:03d}")] = f"init_{s}_{k}"

    def emit(self, shard, phys, log, tx_id, op, key=None, value=None):
        if tx_id not in self.op_seqs:
            self.op_seqs[tx_id] = 0
        self.op_seqs[tx_id] += 1
        self.operations.append(
            (shard, phys, log, tx_id, op, key, value, self.op_seqs[tx_id])
        )
        if op == "COMMIT":
            self.tx_outcomes.append((tx_id, shard, "committed", phys, log))
        elif op == "ABORT":
            self.tx_outcomes.append((tx_id, shard, "aborted", phys, log))

    def normal_single(self, shard):
        tx = self.ids.single()
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tx, "BEGIN")

        nr = random.randint(1, 3)
        kidxs = random.sample(range(KEYS_PER_SHARD), nr)
        keys = [f"s{shard}_k{i:03d}" for i in kidxs]

        for k in keys:
            phys, log = self.clocks[shard].tick()
            v = self.kv.get((shard, k), f"init_{shard}_{k}")
            self.emit(shard, phys, log, tx, "R", k, v)

        if random.random() < 0.4:
            wk = keys[random.randint(0, len(keys) - 1)]
            phys, log = self.clocks[shard].tick()
            nv = f"v_{random.randint(1, 9999999)}"
            self.kv[(shard, wk)] = nv
            self.emit(shard, phys, log, tx, "W", wk, nv)

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tx, "COMMIT")

    def normal_cross(self, s1, s2):
        tx = self.ids.cross()
        for s in [s1, s2]:
            phys, log = self.clocks[s].tick()
            self.emit(s, phys, log, tx, "BEGIN")

        for s in [s1, s2]:
            ki = random.randint(0, KEYS_PER_SHARD - 1)
            k = f"s{s}_k{ki:03d}"
            phys, log = self.clocks[s].tick()
            v = self.kv.get((s, k), f"init_{s}_{ki}")
            self.emit(s, phys, log, tx, "R", k, v)
            if random.random() < 0.5:
                phys, log = self.clocks[s].tick()
                nv = f"v_{random.randint(1, 9999999)}"
                self.kv[(s, k)] = nv
                self.emit(s, phys, log, tx, "W", k, nv)

        for s in [s1, s2]:
            phys, log = self.clocks[s].tick()
            self.emit(s, phys, log, tx, "PREPARE")
        for s in [s1, s2]:
            phys, log = self.clocks[s].tick()
            self.emit(s, phys, log, tx, "COMMIT")

    def inject_write_skew(self, shard):
        t1 = self.ids.single()
        t2 = self.ids.single()
        ka = f"ws_{shard}_a"
        kb = f"ws_{shard}_b"

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t1, "BEGIN")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t1, "R", ka, "50")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t1, "R", kb, "30")

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t2, "BEGIN")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t2, "R", ka, "50")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t2, "R", kb, "30")

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t1, "W", ka, "90")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t1, "COMMIT")

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t2, "W", kb, "60")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t2, "COMMIT")

        return (t1, t2)

    def inject_lost_update(self, shard):
        t1 = self.ids.single()
        t2 = self.ids.single()
        k = f"lu_{shard}"

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t1, "BEGIN")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t1, "R", k, "100")

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t2, "BEGIN")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t2, "R", k, "100")

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t1, "W", k, "110")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t1, "COMMIT")

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t2, "W", k, "120")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t2, "COMMIT")

        return (t1, t2)

    def inject_atomicity_violation(self):
        tx = self.ids.cross()
        idx = self.ids._cross
        k0 = f"av_{idx}_s0"
        k1 = f"av_{idx}_s1"

        for s in [0, 1]:
            phys, log = self.clocks[s].tick()
            self.emit(s, phys, log, tx, "BEGIN")

        phys, log = self.clocks[0].tick()
        self.emit(0, phys, log, tx, "W", k0, "committed_val")
        phys, log = self.clocks[1].tick()
        self.emit(1, phys, log, tx, "W", k1, "should_commit_val")

        for s in [0, 1]:
            phys, log = self.clocks[s].tick()
            self.emit(s, phys, log, tx, "PREPARE")

        phys, log = self.clocks[0].tick()
        self.emit(0, phys, log, tx, "COMMIT")
        phys, log = self.clocks[1].tick()
        self.emit(1, phys, log, tx, "ABORT")

        return tx

    def inject_dirty_read(self, shard):
        tw = self.ids.single()
        tr = self.ids.single()
        k = f"dr_{shard}"

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tw, "BEGIN")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tw, "W", k, "dirty_uncommitted")

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tr, "BEGIN")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tr, "R", k, "dirty_uncommitted")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tr, "COMMIT")

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tw, "ABORT")

        return (tw, tr)

    def inject_non_repeatable_read(self, shard):
        tr = self.ids.single()
        tw = self.ids.single()
        k = f"nr_{shard}"

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tr, "BEGIN")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tr, "R", k, "stable_val")

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tw, "BEGIN")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tw, "W", k, "changed_val")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tw, "COMMIT")

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tr, "R", k, "changed_val")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, tr, "COMMIT")

        return (tr, tw)

    def inject_precedence_cycle(self, shard):
        t1 = self.ids.single()
        t2 = self.ids.single()
        t3 = self.ids.single()
        kx = f"cy_{shard}_x"
        ky = f"cy_{shard}_y"
        kz = f"cy_{shard}_z"

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t1, "BEGIN")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t1, "W", kx, "x1")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t1, "R", ky, "y0")

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t2, "BEGIN")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t2, "W", ky, "y1")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t2, "R", kz, "z0")

        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t3, "BEGIN")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t3, "W", kz, "z1")
        phys, log = self.clocks[shard].tick()
        self.emit(shard, phys, log, t3, "R", kx, "x0")

        for t in [t1, t2, t3]:
            phys, log = self.clocks[shard].tick()
            self.emit(shard, phys, log, t, "COMMIT")

        return (t1, t2, t3)

    def generate(self):
        # Phase 1: 200 normal per shard (T_0001-T_0600)
        for s in range(NUM_SHARDS):
            for _ in range(200):
                self.normal_single(s)

        # Anomalies: write skew on shard 0 and shard 1
        self.inject_write_skew(0)
        self.inject_write_skew(1)

        # Phase 2: 100 normal per shard (T_0605-T_0904)
        for s in range(NUM_SHARDS):
            for _ in range(100):
                self.normal_single(s)

        # Anomaly: lost update on shard 2
        self.inject_lost_update(2)

        # 50 normal cross-shard (X_0001-X_0050)
        for _ in range(50):
            s1, s2 = sorted(random.sample(range(NUM_SHARDS), 2))
            self.normal_cross(s1, s2)

        # Anomalies: atomicity violations (X_0051, X_0052)
        self.inject_atomicity_violation()
        self.inject_atomicity_violation()

        # Phase 3: 100 normal per shard (T_0907-T_1206)
        for s in range(NUM_SHARDS):
            for _ in range(100):
                self.normal_single(s)

        # Anomaly: dirty read on shard 0
        self.inject_dirty_read(0)

        # Anomaly: non-repeatable read on shard 1
        self.inject_non_repeatable_read(1)

        # Phase 4: 100 normal per shard (T_1211-T_1510)
        for s in range(NUM_SHARDS):
            for _ in range(100):
                self.normal_single(s)

        # Anomaly: precedence cycle on shard 2
        self.inject_precedence_cycle(2)

        # Phase 5: 100 normal per shard (T_1514-T_1813)
        for s in range(NUM_SHARDS):
            for _ in range(100):
                self.normal_single(s)

        # 50 more normal cross-shard (X_0053-X_0102)
        for _ in range(50):
            s1, s2 = sorted(random.sample(range(NUM_SHARDS), 2))
            self.normal_cross(s1, s2)

        # Phase 6: 100 normal per shard (T_1814-T_2113)
        for s in range(NUM_SHARDS):
            for _ in range(100):
                self.normal_single(s)

        self.write_to_postgres()

    def _run_psql(self, sql_file_path, label):
        """Run SQL file via psql with error checking."""
        result = subprocess.run(
            ["psql", "-v", "ON_ERROR_STOP=1",
             "-U", "auditor", "-d", "txstore", "-f", sql_file_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"STDERR ({label}): {result.stderr}", file=sys.stderr)
            print(f"STDOUT ({label}): {result.stdout}", file=sys.stderr)
            raise RuntimeError(f"SQL load failed for {label}")
        print(f"Loaded {label} successfully")

    def write_to_postgres(self):
        # === Part 1: Schema + metadata ===
        schema_path = "/tmp/load_schema.sql"
        with open(schema_path, "w") as f:
            f.write("CREATE TABLE shards (\n")
            f.write("    shard_id INTEGER PRIMARY KEY,\n")
            f.write("    region TEXT NOT NULL\n")
            f.write(");\n\n")

            f.write("CREATE TABLE operations (\n")
            f.write("    op_id SERIAL PRIMARY KEY,\n")
            f.write("    shard_id INTEGER NOT NULL REFERENCES shards(shard_id),\n")
            f.write("    tx_id TEXT NOT NULL,\n")
            f.write("    seq_num INTEGER NOT NULL,\n")
            f.write("    hlc_physical BIGINT NOT NULL,\n")
            f.write("    hlc_logical INTEGER NOT NULL,\n")
            f.write("    op_type TEXT NOT NULL,\n")
            f.write("    target_key TEXT,\n")
            f.write("    op_value TEXT\n")
            f.write(");\n\n")

            f.write("CREATE TABLE tx_outcomes (\n")
            f.write("    tx_id TEXT NOT NULL,\n")
            f.write("    shard_id INTEGER NOT NULL REFERENCES shards(shard_id),\n")
            f.write("    outcome TEXT NOT NULL,\n")
            f.write("    hlc_physical BIGINT,\n")
            f.write("    hlc_logical INTEGER,\n")
            f.write("    PRIMARY KEY (tx_id, shard_id)\n")
            f.write(");\n\n")

            f.write("CREATE TABLE cluster_metadata (\n")
            f.write("    param_name TEXT PRIMARY KEY,\n")
            f.write("    param_value TEXT NOT NULL\n")
            f.write(");\n\n")

            f.write("CREATE INDEX idx_ops_tx ON operations(tx_id);\n")
            f.write("CREATE INDEX idx_ops_shard ON operations(shard_id);\n")
            f.write("CREATE INDEX idx_ops_key ON operations(target_key) "
                    "WHERE target_key IS NOT NULL;\n")
            f.write("CREATE INDEX idx_ops_type ON operations(op_type);\n\n")

            for s in range(NUM_SHARDS):
                f.write(f"INSERT INTO shards VALUES ({s}, 'region_{s}');\n")

            metadata = [
                ("consistency_model", "strict_serializability"),
                ("isolation_level", "serializable"),
                ("mvcc_enabled", "true"),
                ("timestamp_type", "hybrid_logical_clock"),
                ("cross_shard_protocol", "two_phase_commit"),
                ("num_shards", "3"),
                ("replication_factor", "3"),
            ]
            for k, v in metadata:
                f.write(f"INSERT INTO cluster_metadata VALUES ('{k}', '{v}');\n")

        self._run_psql(schema_path, "schema")
        os.remove(schema_path)

        # === Part 2: Operations via COPY ===
        ops_path = "/tmp/load_operations.sql"
        with open(ops_path, "w") as f:
            f.write(
                "COPY operations "
                "(shard_id, tx_id, seq_num, hlc_physical, hlc_logical, "
                "op_type, target_key, op_value) FROM stdin;\n"
            )
            for op in self.operations:
                shard, phys, log, tx_id, op_type, key, value, seq = op
                key_str = key if key is not None else "\\N"
                value_str = str(value) if value is not None else "\\N"
                f.write(
                    f"{shard}\t{tx_id}\t{seq}\t{phys}\t{log}\t"
                    f"{op_type}\t{key_str}\t{value_str}\n"
                )
            f.write("\\.\n")

        self._run_psql(ops_path, "operations")
        os.remove(ops_path)

        # === Part 3: TX Outcomes via COPY ===
        outcomes_path = "/tmp/load_outcomes.sql"
        with open(outcomes_path, "w") as f:
            f.write(
                "COPY tx_outcomes "
                "(tx_id, shard_id, outcome, hlc_physical, hlc_logical) "
                "FROM stdin;\n"
            )
            for outcome in self.tx_outcomes:
                tx_id, shard, status, phys, log = outcome
                f.write(f"{tx_id}\t{shard}\t{status}\t{phys}\t{log}\n")
            f.write("\\.\n")

        self._run_psql(outcomes_path, "outcomes")
        os.remove(outcomes_path)

        # === Verification ===
        verify_result = subprocess.run(
            ["psql", "-U", "auditor", "-d", "txstore", "-t", "-A", "-c",
             "SELECT COUNT(*) FROM tx_outcomes;"],
            capture_output=True, text=True,
        )
        outcome_count = int(verify_result.stdout.strip())

        verify_result2 = subprocess.run(
            ["psql", "-U", "auditor", "-d", "txstore", "-t", "-A", "-c",
             "SELECT COUNT(DISTINCT tx_id) FROM operations;"],
            capture_output=True, text=True,
        )
        tx_count = int(verify_result2.stdout.strip())

        # Check for mixed-outcome transactions (atomicity violations)
        verify_result3 = subprocess.run(
            ["psql", "-U", "auditor", "-d", "txstore", "-t", "-A", "-c",
             "SELECT COUNT(*) FROM (SELECT tx_id FROM tx_outcomes "
             "GROUP BY tx_id HAVING COUNT(DISTINCT outcome) > 1) sub;"],
            capture_output=True, text=True,
        )
        mixed_count = int(verify_result3.stdout.strip())

        print(f"Loaded {len(self.operations)} operations, "
              f"{len(self.tx_outcomes)} outcomes")
        print(f"Distinct transactions: {tx_count}")
        print(f"tx_outcomes rows: {outcome_count}")
        print(f"Mixed-outcome transactions: {mixed_count}")

        if outcome_count < 2000:
            raise RuntimeError(
                f"tx_outcomes has only {outcome_count} rows, expected ~2317"
            )
        if mixed_count < 2:
            raise RuntimeError(
                f"Only {mixed_count} mixed-outcome txs, expected 2"
            )


if __name__ == "__main__":
    Generator().generate()
