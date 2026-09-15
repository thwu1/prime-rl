
import json
import os
import struct
import sys
import zlib

import pytest


def _expected_committed_state():
    """Replay all 120 committed entries to compute expected KV state."""
    state = {}
    for i in range(1, 121):
        if i % 10 == 0:
            state.pop(f"key_{i - 5}", None)
        else:
            state[f"key_{i}"] = f"val_{i}"
    return state


class TestCommittedState:
    def test_file_exists(self):
        assert os.path.isfile("/app/committed_state.json"), \
            "committed_state.json not found"

    def test_state_correct(self):
        with open("/app/committed_state.json") as f:
            state = json.load(f)
        expected = _expected_committed_state()
        assert state == expected, (
            f"State mismatch: got {len(state)} keys, expected {len(expected)}"
        )

    def test_key_count(self):
        with open("/app/committed_state.json") as f:
            state = json.load(f)
        assert len(state) == 96

    def test_no_stale_values(self):
        """Stale term-2 payloads from node_1 must not appear."""
        with open("/app/committed_state.json") as f:
            state = json.load(f)
        for i in [91, 92, 93]:
            assert state.get(f"key_{i}") != f"stale_{i}", \
                f"key_{i} has stale value from superseded term 2"
            assert state.get(f"key_{i}") == f"val_{i}", \
                f"key_{i} should have committed term-3 value"

    def test_corrupted_entries_recovered(self):
        """Entries 67 and 103 were corrupted on individual nodes but
        should be recovered via cross-referencing other nodes."""
        with open("/app/committed_state.json") as f:
            state = json.load(f)
        assert state.get("key_67") == "val_67", \
            "key_67 missing — entry 67 should be recovered from another node"
        assert state.get("key_103") == "val_103", \
            "key_103 missing — entry 103 should be recovered from another node"

    def test_deleted_keys_absent(self):
        """Keys targeted by DEL commands must be absent."""
        with open("/app/committed_state.json") as f:
            state = json.load(f)
        for i in range(10, 121, 10):
            k = f"key_{i - 5}"
            assert k not in state, f"{k} should have been deleted by entry {i}"


class TestReconciliationReport:
    def test_file_exists(self):
        assert os.path.isfile("/app/reconciliation.json"), \
            "reconciliation.json not found"

    def test_commit_index(self):
        with open("/app/reconciliation.json") as f:
            report = json.load(f)
        assert report["commit_index"] == 120

    def test_committed_entry_count(self):
        with open("/app/reconciliation.json") as f:
            report = json.load(f)
        assert report["committed_entry_count"] == 120

    def test_stale_entries_detected(self):
        with open("/app/reconciliation.json") as f:
            report = json.load(f)
        assert "node_1" in report["stale_entries"], \
            "node_1 stale entries not detected"
        stale = set(report["stale_entries"]["node_1"])
        assert stale == {91, 92, 93}, \
            f"Expected stale {{91,92,93}} on node_1, got {stale}"

    def test_no_other_stale_nodes(self):
        with open("/app/reconciliation.json") as f:
            report = json.load(f)
        stale_nodes = set(report["stale_entries"].keys())
        assert stale_nodes == {"node_1"}, \
            f"Only node_1 should have stale entries, got {stale_nodes}"

    def test_corrupted_entries_node0(self):
        with open("/app/reconciliation.json") as f:
            report = json.load(f)
        assert 67 in report["corrupted_entries"].get("node_0", []), \
            "Entry 67 CRC corruption on node_0 not detected"

    def test_corrupted_entries_node2(self):
        with open("/app/reconciliation.json") as f:
            report = json.load(f)
        assert 103 in report["corrupted_entries"].get("node_2", []), \
            "Entry 103 CRC corruption on node_2 not detected"

    def test_cross_referenced_recoveries(self):
        with open("/app/reconciliation.json") as f:
            report = json.load(f)
        xref = set(report["cross_referenced_recoveries"])
        assert 67 in xref, "Entry 67 cross-reference recovery not reported"
        assert 103 in xref, "Entry 103 cross-reference recovery not reported"


class TestAntiCheat:
    """Generate a completely different cluster and verify the reconciler
    handles unseen data correctly — not hardcoded answers."""

    def test_fresh_cluster_reconciliation(self, tmp_path):
        import importlib

        SEG_MAGIC = b'RLOG'
        VER = 1

        def _mk_entry(idx, term, payload_str):
            payload = payload_str.encode('utf-8')
            buf = struct.pack('<Q', idx)
            buf += struct.pack('<Q', term)
            buf += struct.pack('<q', 1700000000000000000 + idx * 1000000)
            buf += struct.pack('<I', len(payload))
            buf += payload
            crc = zlib.crc32(buf) & 0xFFFFFFFF
            buf += struct.pack('<I', crc)
            return buf

        def _mk_segment(path, entries_tuples):
            with open(path, 'wb') as f:
                f.write(SEG_MAGIC)
                f.write(struct.pack('<H', VER))
                f.write(struct.pack('<Q', entries_tuples[0][0]))
                f.write(struct.pack('<I', len(entries_tuples)))
                for idx, term, payload in entries_tuples:
                    f.write(_mk_entry(idx, term, payload))

        # Fresh scenario: 3 nodes, 30 entries, 2 terms
        # Term 1: entries 1-15 on all 3 nodes (committed)
        # Term 2: entries 16-30 on nodes 0,1 (committed, majority 2/3)
        # Node 2: stale entries 16-18 from term 1 (different payloads)
        # Node 0: entry 8 corrupted (CRC)
        committed = []
        for i in range(1, 31):
            term = 1 if i <= 15 else 2
            if i % 10 == 0:
                committed.append((i, term, f'DEL key_{i - 5}'))
            else:
                committed.append((i, term, f'SET key_{i} val_{i}'))

        for nname in ['node_0', 'node_1', 'node_2']:
            os.makedirs(str(tmp_path / nname))

        # Node 0: entries 1-30, entry 8 corrupted
        _mk_segment(str(tmp_path / 'node_0' / 'segment_0000000001.wal'),
                     committed[:15])
        _mk_segment(str(tmp_path / 'node_0' / 'segment_0000000016.wal'),
                     committed[15:])
        seg0 = str(tmp_path / 'node_0' / 'segment_0000000001.wal')
        with open(seg0, 'rb') as f:
            d = bytearray(f.read())
        off = 18
        for _ in range(7):
            plen = struct.unpack_from('<I', d, off + 24)[0]
            off += 28 + plen + 4
        d[off + 28 + 2] ^= 0xFF
        with open(seg0, 'wb') as f:
            f.write(d)

        # Node 1: entries 1-30, clean
        _mk_segment(str(tmp_path / 'node_1' / 'segment_0000000001.wal'),
                     committed[:15])
        _mk_segment(str(tmp_path / 'node_1' / 'segment_0000000016.wal'),
                     committed[15:])

        # Node 2: entries 1-15 (term 1), stale entries 16-18 (term 1)
        _mk_segment(str(tmp_path / 'node_2' / 'segment_0000000001.wal'),
                     committed[:15])
        stale = [(i, 1, f'SET key_{i} stale_{i}') for i in range(16, 19)]
        _mk_segment(str(tmp_path / 'node_2' / 'segment_0000000016.wal'),
                     stale)

        # Import and run solver's reconciler
        sys.path.insert(0, '/app')
        wr = importlib.import_module('wal_reconciler')
        importlib.reload(wr)
        state, report = wr.reconcile(str(tmp_path))

        # Compute expected state
        expected = {}
        for i in range(1, 31):
            if i % 10 == 0:
                expected.pop(f'key_{i - 5}', None)
            else:
                expected[f'key_{i}'] = f'val_{i}'

        assert state == expected, \
            f"Fresh cluster: state mismatch, got {len(state)} keys expected {len(expected)}"
        assert report['commit_index'] == 30
        assert 8 in report.get('cross_referenced_recoveries', []), \
            "Entry 8 cross-reference not detected on fresh data"
        assert 'node_2' in report.get('stale_entries', {}), \
            "Stale entries on node_2 not detected"
        stale_on_2 = set(report['stale_entries']['node_2'])
        for idx in [16, 17, 18]:
            assert idx in stale_on_2, \
                f"Entry {idx} should be stale on node_2"
        for i in [16, 17, 18]:
            assert state.get(f'key_{i}') != f'stale_{i}', \
                f"key_{i} has stale value on fresh data"
