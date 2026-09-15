#!/usr/bin/env python3
"""
Generate transaction logs for a 3-shard MVCC key-value store.
Deterministic (seeded) with known consistency anomalies injected.
"""
import random
import json
import os

SEED = 314159
NUM_SHARDS = 3
KEYS_PER_SHARD = 50
OUTPUT_DIR = "/app/logs"

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
        return f"{self.physical}.{self.logical}"


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
        self.logs = {s: [] for s in range(NUM_SHARDS)}
        self.kv = {}
        for s in range(NUM_SHARDS):
            for k in range(KEYS_PER_SHARD):
                self.kv[(s, f"s{s}_k{k:03d}")] = f"init_{s}_{k}"

    def emit(self, shard, ts, tx_id, op, key=None, value=None):
        parts = [ts, tx_id, op]
        if key is not None:
            parts.append(key)
        if value is not None:
            parts.append(str(value))
        self.logs[shard].append(" ".join(parts))

    def normal_single(self, shard):
        tx = self.ids.single()
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tx, "BEGIN")

        nr = random.randint(1, 3)
        kidxs = random.sample(range(KEYS_PER_SHARD), nr)
        keys = [f"s{shard}_k{i:03d}" for i in kidxs]

        for k in keys:
            ts = self.clocks[shard].tick()
            v = self.kv.get((shard, k), f"init_{shard}_{k}")
            self.emit(shard, ts, tx, "R", k, v)

        if random.random() < 0.4:
            wk = keys[random.randint(0, len(keys) - 1)]
            ts = self.clocks[shard].tick()
            nv = f"v_{random.randint(1, 9999999)}"
            self.kv[(shard, wk)] = nv
            self.emit(shard, ts, tx, "W", wk, nv)

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tx, "COMMIT")

    def normal_cross(self, s1, s2):
        tx = self.ids.cross()
        for s in [s1, s2]:
            ts = self.clocks[s].tick()
            self.emit(s, ts, tx, "BEGIN")

        for s in [s1, s2]:
            ki = random.randint(0, KEYS_PER_SHARD - 1)
            k = f"s{s}_k{ki:03d}"
            ts = self.clocks[s].tick()
            v = self.kv.get((s, k), f"init_{s}_{ki}")
            self.emit(s, ts, tx, "R", k, v)
            if random.random() < 0.5:
                ts = self.clocks[s].tick()
                nv = f"v_{random.randint(1, 9999999)}"
                self.kv[(s, k)] = nv
                self.emit(s, ts, tx, "W", k, nv)

        for s in [s1, s2]:
            ts = self.clocks[s].tick()
            self.emit(s, ts, tx, "PREPARE")
        for s in [s1, s2]:
            ts = self.clocks[s].tick()
            self.emit(s, ts, tx, "COMMIT")

    def inject_write_skew(self, shard):
        t1 = self.ids.single()
        t2 = self.ids.single()
        ka = f"ws_{shard}_a"
        kb = f"ws_{shard}_b"

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t1, "BEGIN")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t1, "R", ka, "50")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t1, "R", kb, "30")

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t2, "BEGIN")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t2, "R", ka, "50")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t2, "R", kb, "30")

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t1, "W", ka, "90")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t1, "COMMIT")

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t2, "W", kb, "60")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t2, "COMMIT")

        return (t1, t2)

    def inject_lost_update(self, shard):
        t1 = self.ids.single()
        t2 = self.ids.single()
        k = f"lu_{shard}"

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t1, "BEGIN")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t1, "R", k, "100")

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t2, "BEGIN")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t2, "R", k, "100")

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t1, "W", k, "110")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t1, "COMMIT")

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t2, "W", k, "120")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t2, "COMMIT")

        return (t1, t2)

    def inject_atomicity_violation(self):
        tx = self.ids.cross()
        idx = self.ids._cross
        k0 = f"av_{idx}_s0"
        k1 = f"av_{idx}_s1"

        for s in [0, 1]:
            ts = self.clocks[s].tick()
            self.emit(s, ts, tx, "BEGIN")

        ts = self.clocks[0].tick()
        self.emit(0, ts, tx, "W", k0, "committed_val")
        ts = self.clocks[1].tick()
        self.emit(1, ts, tx, "W", k1, "should_commit_val")

        for s in [0, 1]:
            ts = self.clocks[s].tick()
            self.emit(s, ts, tx, "PREPARE")

        ts = self.clocks[0].tick()
        self.emit(0, ts, tx, "COMMIT")
        ts = self.clocks[1].tick()
        self.emit(1, ts, tx, "ABORT")

        return tx

    def inject_dirty_read(self, shard):
        tw = self.ids.single()
        tr = self.ids.single()
        k = f"dr_{shard}"

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tw, "BEGIN")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tw, "W", k, "dirty_uncommitted")

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tr, "BEGIN")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tr, "R", k, "dirty_uncommitted")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tr, "COMMIT")

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tw, "ABORT")

        return (tw, tr)

    def inject_non_repeatable_read(self, shard):
        tr = self.ids.single()
        tw = self.ids.single()
        k = f"nr_{shard}"

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tr, "BEGIN")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tr, "R", k, "stable_val")

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tw, "BEGIN")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tw, "W", k, "changed_val")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tw, "COMMIT")

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tr, "R", k, "changed_val")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, tr, "COMMIT")

        return (tr, tw)

    def inject_precedence_cycle(self, shard):
        t1 = self.ids.single()
        t2 = self.ids.single()
        t3 = self.ids.single()
        kx = f"cy_{shard}_x"
        ky = f"cy_{shard}_y"
        kz = f"cy_{shard}_z"

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t1, "BEGIN")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t1, "W", kx, "x1")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t1, "R", ky, "y0")

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t2, "BEGIN")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t2, "W", ky, "y1")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t2, "R", kz, "z0")

        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t3, "BEGIN")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t3, "W", kz, "z1")
        ts = self.clocks[shard].tick()
        self.emit(shard, ts, t3, "R", kx, "x0")

        for t in [t1, t2, t3]:
            ts = self.clocks[shard].tick()
            self.emit(shard, ts, t, "COMMIT")

        return (t1, t2, t3)

    def generate(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # Phase 1: 200 normal per shard (T_0001-T_0600)
        for s in range(NUM_SHARDS):
            for _ in range(200):
                self.normal_single(s)

        # Anomalies: write skew on shard 0 (T_0601, T_0602) and shard 1 (T_0603, T_0604)
        self.inject_write_skew(0)
        self.inject_write_skew(1)

        # Phase 2: 100 normal per shard (T_0605-T_0904)
        for s in range(NUM_SHARDS):
            for _ in range(100):
                self.normal_single(s)

        # Anomaly: lost update on shard 2 (T_0905, T_0906)
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

        # Anomaly: dirty read on shard 0 (T_1207 writer, T_1208 reader)
        self.inject_dirty_read(0)

        # Anomaly: non-repeatable read on shard 1 (T_1209 reader, T_1210 writer)
        self.inject_non_repeatable_read(1)

        # Phase 4: 100 normal per shard (T_1211-T_1510)
        for s in range(NUM_SHARDS):
            for _ in range(100):
                self.normal_single(s)

        # Anomaly: precedence cycle on shard 2 (T_1511, T_1512, T_1513)
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

        # Write log files
        for s in range(NUM_SHARDS):
            with open(f"{OUTPUT_DIR}/shard_{s}.log", "w") as f:
                f.write("\n".join(self.logs[s]) + "\n")

        # Write schema
        schema = {
            "format": "TIMESTAMP TX_ID OP [KEY [VALUE]]",
            "timestamp_format": "physical_time.logical_counter (Hybrid Logical Clock)",
            "operations": {
                "BEGIN": "Transaction start",
                "R": "Read: R KEY VALUE — the value the transaction observed",
                "W": "Write: W KEY VALUE — the value the transaction wrote",
                "PREPARE": "2PC prepare phase (cross-shard transactions only)",
                "COMMIT": "Transaction committed successfully",
                "ABORT": "Transaction aborted / rolled back"
            },
            "transaction_id_conventions": {
                "T_NNNN": "Single-shard transaction",
                "X_NNNN": "Cross-shard transaction (operations appear in multiple shard logs)"
            },
            "shards": NUM_SHARDS,
            "log_files": [f"shard_{s}.log" for s in range(NUM_SHARDS)],
            "consistency_model": "strict_serializability",
            "cross_shard_protocol": "two_phase_commit",
            "notes": [
                "Each shard log contains operations local to that shard, ordered by HLC timestamp.",
                "Cross-shard transactions use two-phase commit: BEGIN on all shards, operations, PREPARE on all, then COMMIT/ABORT on all.",
                "The store uses MVCC internally. Reads return the value that was visible to the transaction.",
                "Initial key values are implicit; a read of a never-written key returns its initial value."
            ]
        }
        with open("/app/schema.json", "w") as f:
            json.dump(schema, f, indent=2)

        print(f"Generated {self.ids._single} single-shard, {self.ids._cross} cross-shard transactions")
        for s in range(NUM_SHARDS):
            print(f"  Shard {s}: {len(self.logs[s])} log lines")


if __name__ == "__main__":
    Generator().generate()
