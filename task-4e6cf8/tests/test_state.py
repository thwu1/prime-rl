#!/usr/bin/env python3
"""Tests for SQLite WAL forensics, recovery, and Litestream replication.

All expected values are derived independently from the raw WAL binary
at test time — no pre-computed answer files are used.
"""

import json
import os
import shutil
import sqlite3
import struct
import subprocess

import pytest

DATA_DIR = '/app/data'
TOOL_PATH = '/app/wal_recovery.py'
REPORT_PATH = os.path.join(DATA_DIR, 'wal_report.json')
RECOVERED_PATH = os.path.join(DATA_DIR, 'recovered.db')
WAL_PATH = os.path.join(DATA_DIR, 'sensor_data.db-wal')
DB_PATH = os.path.join(DATA_DIR, 'sensor_data.db')
VALIDATION_SCRIPT = '/app/validate_replication.sh'
LITESTREAM_CONFIG = '/app/litestream.yml'
REPLICA_DIR = os.path.join(DATA_DIR, 'replica')
RESTORED_PATH = os.path.join(DATA_DIR, 'replica_restored.db')
REPLICATION_REPORT = os.path.join(DATA_DIR, 'replication_report.json')


# ---------------------------------------------------------------------------
# Reference WAL parser (independent ground truth computation)
# ---------------------------------------------------------------------------

def _ref_wal_checksum(data, s0=0, s1=0, little_endian=True):
    """Reference implementation of the SQLite WAL checksum algorithm."""
    fmt = '<I' if little_endian else '>I'
    mask = 0xFFFFFFFF
    for i in range(0, len(data), 8):
        w0 = struct.unpack(fmt, data[i:i + 4])[0]
        w1 = struct.unpack(fmt, data[i + 4:i + 8])[0]
        s0 = (s0 + w0 + s1) & mask
        s1 = (s1 + w1 + s0) & mask
    return s0, s1


def _ref_parse_wal(wal_path):
    """Parse WAL independently and return all structural information."""
    with open(wal_path, 'rb') as f:
        wal = f.read()

    magic = struct.unpack('>I', wal[0:4])[0]
    little_endian = (magic == 0x377f0682)
    page_size = struct.unpack('>I', wal[8:12])[0]
    frame_hdr_size = 24
    frame_size = frame_hdr_size + page_size
    total_frames = (len(wal) - 32) // frame_size
    salt1 = struct.unpack('>I', wal[16:20])[0]
    salt2 = struct.unpack('>I', wal[20:24])[0]

    # Verify header checksum
    h_s0, h_s1 = _ref_wal_checksum(wal[0:24], little_endian=little_endian)
    hdr_ck1 = struct.unpack('>I', wal[24:28])[0]
    hdr_ck2 = struct.unpack('>I', wal[28:32])[0]
    assert h_s0 == hdr_ck1 and h_s1 == hdr_ck2, "WAL header checksum bad"

    running_s0, running_s1 = h_s0, h_s1
    first_invalid = None
    valid_count = 0
    tx_count = 0
    frames = []
    commit_frame_indices = []
    committed_pages = {}
    current_tx_pages = {}

    for i in range(total_frames):
        offset = 32 + i * frame_size
        pgno = struct.unpack('>I', wal[offset:offset + 4])[0]
        db_size = struct.unpack('>I', wal[offset + 4:offset + 8])[0]
        f_salt1 = struct.unpack('>I', wal[offset + 8:offset + 12])[0]
        f_salt2 = struct.unpack('>I', wal[offset + 12:offset + 16])[0]
        f_ck1 = struct.unpack('>I', wal[offset + 16:offset + 20])[0]
        f_ck2 = struct.unpack('>I', wal[offset + 20:offset + 24])[0]

        page_data = wal[offset + frame_hdr_size:offset + frame_size]
        salt_ok = (f_salt1 == salt1 and f_salt2 == salt2)

        cksum_input = wal[offset:offset + 8] + page_data
        comp_s0, comp_s1 = _ref_wal_checksum(
            cksum_input, running_s0, running_s1, little_endian
        )
        checksum_valid = (comp_s0 == f_ck1 and comp_s1 == f_ck2)
        is_commit = (db_size > 0)
        is_valid = salt_ok and checksum_valid

        frames.append({
            'index': i, 'page_number': pgno,
            'is_commit': is_commit, 'checksum_valid': is_valid,
        })

        if is_valid:
            valid_count += 1
            running_s0, running_s1 = comp_s0, comp_s1
            current_tx_pages[pgno] = page_data
            if is_commit:
                tx_count += 1
                commit_frame_indices.append(i)
                committed_pages.update(current_tx_pages)
                current_tx_pages = {}
        else:
            if first_invalid is None:
                first_invalid = i
            break

    return {
        'total_frames': total_frames,
        'valid_frames': valid_count,
        'first_invalid': first_invalid,
        'valid_transactions': tx_count,
        'commit_frame_indices': commit_frame_indices,
        'frames': frames,
        'committed_pages': committed_pages,
        'page_size': page_size,
    }


def _ref_recover_db(db_path, committed_pages, page_size):
    """Replay committed WAL pages onto base DB and return expected rows."""
    tmp_path = '/tmp/_ref_recovered.db'
    shutil.copy2(db_path, tmp_path)
    # Remove any WAL/SHM for the temp copy
    for suffix in ['-wal', '-shm']:
        p = tmp_path + suffix
        if os.path.exists(p):
            os.remove(p)

    with open(tmp_path, 'r+b') as f:
        for pgno, pdata in committed_pages.items():
            f.seek((pgno - 1) * page_size)
            f.write(pdata)
        # Switch from WAL to rollback journal mode
        f.seek(18)
        f.write(b'\x01\x01')

    conn = sqlite3.connect(tmp_path)
    rows = conn.execute("SELECT * FROM sensors ORDER BY id").fetchall()
    conn.close()
    os.remove(tmp_path)
    return [list(r) for r in rows]


# Cache parsed results for the session
_ref_cache = {}


def _get_ref():
    if 'parsed' not in _ref_cache:
        _ref_cache['parsed'] = _ref_parse_wal(WAL_PATH)
    return _ref_cache['parsed']


def _get_ref_rows():
    if 'rows' not in _ref_cache:
        ref = _get_ref()
        _ref_cache['rows'] = _ref_recover_db(
            DB_PATH, ref['committed_pages'], ref['page_size']
        )
    return _ref_cache['rows']


# ---------------------------------------------------------------------------
# Run the student's tools
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session', autouse=True)
def run_tools():
    """Run recovery and validation tools before all tests."""
    # Part 1: WAL recovery (required — failure blocks all tests)
    assert os.path.isfile(TOOL_PATH), \
        f"Recovery tool not found at {TOOL_PATH}"
    result = subprocess.run(
        ['python3', TOOL_PATH, DB_PATH],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        pytest.fail(
            f"Tool exited with code {result.returncode}\n"
            f"stdout: {result.stdout[:2000]}\n"
            f"stderr: {result.stderr[:2000]}"
        )

    # Part 2: Litestream validation (best effort — individual tests catch failures)
    if os.path.isfile(VALIDATION_SCRIPT):
        try:
            subprocess.run(
                ['bash', VALIDATION_SCRIPT],
                capture_output=True, text=True, timeout=180
            )
        except Exception:
            pass  # Part 2 tests will fail on missing output files


def load_report():
    with open(REPORT_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Output file existence
# ---------------------------------------------------------------------------
class TestOutputFiles:
    def test_report_exists(self):
        assert os.path.isfile(REPORT_PATH), "wal_report.json not generated"

    def test_recovered_db_exists(self):
        assert os.path.isfile(RECOVERED_PATH), "recovered.db not generated"


# ---------------------------------------------------------------------------
# WAL header parsing
# ---------------------------------------------------------------------------
class TestWALHeaderParsing:
    def test_magic_number(self):
        report = load_report()
        with open(WAL_PATH, 'rb') as f:
            expected = struct.unpack('>I', f.read(4))[0]
        assert report['header']['magic'] == expected

    def test_page_size(self):
        report = load_report()
        assert report['header']['page_size'] == 4096

    def test_version(self):
        report = load_report()
        assert report['header']['version'] == 3007000

    def test_salt_values(self):
        report = load_report()
        with open(WAL_PATH, 'rb') as f:
            hdr = f.read(32)
        salt1 = struct.unpack('>I', hdr[16:20])[0]
        salt2 = struct.unpack('>I', hdr[20:24])[0]
        assert report['header']['salt1'] == salt1
        assert report['header']['salt2'] == salt2

    def test_checkpoint_seq(self):
        report = load_report()
        with open(WAL_PATH, 'rb') as f:
            f.seek(12)
            expected = struct.unpack('>I', f.read(4))[0]
        assert report['header']['checkpoint_seq'] == expected


# ---------------------------------------------------------------------------
# Corruption detection (verified against reference parser)
# ---------------------------------------------------------------------------
class TestCorruptionDetection:
    def test_total_frame_count(self):
        report = load_report()
        ref = _get_ref()
        assert report['total_frames'] == ref['total_frames']

    def test_corruption_detected(self):
        report = load_report()
        assert report['corrupted_frames'] > 0

    def test_first_invalid_frame_index(self):
        report = load_report()
        ref = _get_ref()
        assert report['first_invalid_frame'] == ref['first_invalid']

    def test_valid_frame_count(self):
        report = load_report()
        ref = _get_ref()
        assert report['valid_frames'] == ref['valid_frames']

    def test_frame_validity_flags(self):
        report = load_report()
        ref = _get_ref()
        corrupt_idx = ref['first_invalid']
        for frame in report['frames']:
            if frame['index'] < corrupt_idx:
                assert frame['checksum_valid'] is True, \
                    f"Frame {frame['index']} should be valid"
            elif frame['index'] == corrupt_idx:
                assert frame['checksum_valid'] is False, \
                    f"Frame {frame['index']} should be invalid (corrupted)"

    def test_frames_array_completeness(self):
        """Frames array should cover at least through the first invalid frame."""
        report = load_report()
        ref = _get_ref()
        expected_min_len = ref['first_invalid'] + 1
        assert len(report['frames']) >= expected_min_len


# ---------------------------------------------------------------------------
# Transaction detection (verified against reference parser)
# ---------------------------------------------------------------------------
class TestTransactionDetection:
    def test_valid_transaction_count(self):
        report = load_report()
        ref = _get_ref()
        assert report['valid_transactions'] == ref['valid_transactions']

    def test_commit_frames_marked(self):
        report = load_report()
        ref = _get_ref()
        for frame in report['frames']:
            if frame['index'] in ref['commit_frame_indices']:
                assert frame['is_commit'] is True, \
                    f"Frame {frame['index']} should be a commit frame"


# ---------------------------------------------------------------------------
# Binary parsing accuracy (anti-cheat)
# ---------------------------------------------------------------------------
class TestBinaryParsing:
    def test_frame_page_numbers(self):
        """Independently read WAL and verify page numbers match report."""
        report = load_report()
        with open(WAL_PATH, 'rb') as f:
            wal_data = f.read()
        page_size = struct.unpack('>I', wal_data[8:12])[0]
        frame_size = 24 + page_size
        for frame in report['frames']:
            idx = frame['index']
            offset = 32 + idx * frame_size
            expected_pgno = struct.unpack('>I', wal_data[offset:offset + 4])[0]
            assert frame['page_number'] == expected_pgno, \
                f"Frame {idx}: expected page {expected_pgno}, " \
                f"got {frame['page_number']}"

    def test_commit_markers_match_binary(self):
        """Verify is_commit flags match actual db_size fields in WAL."""
        report = load_report()
        with open(WAL_PATH, 'rb') as f:
            wal_data = f.read()
        page_size = struct.unpack('>I', wal_data[8:12])[0]
        frame_size = 24 + page_size
        for frame in report['frames']:
            idx = frame['index']
            offset = 32 + idx * frame_size
            db_size = struct.unpack('>I', wal_data[offset + 4:offset + 8])[0]
            expected_commit = db_size > 0
            assert frame['is_commit'] == expected_commit, \
                f"Frame {idx}: is_commit should be {expected_commit}"


# ---------------------------------------------------------------------------
# Database recovery (verified against independent WAL replay)
# ---------------------------------------------------------------------------
class TestDatabaseRecovery:
    def test_integrity_check(self):
        conn = sqlite3.connect(RECOVERED_PATH)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        assert result[0] == 'ok', f"Integrity check failed: {result}"

    def test_schema_preserved(self):
        conn = sqlite3.connect(RECOVERED_PATH)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()
        assert 'sensors' in [t[0] for t in tables]

    def test_index_preserved(self):
        conn = sqlite3.connect(RECOVERED_PATH)
        indices = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        conn.close()
        assert 'idx_sensors_loc' in [i[0] for i in indices]

    def test_data_matches_reference_replay(self):
        """Compare recovered data against independent WAL replay."""
        expected_rows = _get_ref_rows()
        conn = sqlite3.connect(RECOVERED_PATH)
        rows = conn.execute("SELECT * FROM sensors ORDER BY id").fetchall()
        conn.close()

        actual = [list(r) for r in rows]
        assert len(actual) == len(expected_rows), \
            f"Row count: expected {len(expected_rows)}, got {len(actual)}"
        for i, (a, e) in enumerate(zip(actual, expected_rows)):
            assert a[0] == e[0], f"Row {i} id: {a[0]} != {e[0]}"
            assert a[1] == e[1], f"Row {i} name: {a[1]} != {e[1]}"
            assert a[2] == e[2], f"Row {i} location: {a[2]} != {e[2]}"
            assert abs(a[3] - e[3]) < 1e-10, \
                f"Row {i} reading: {a[3]} != {e[3]}"
            assert a[4] == e[4], f"Row {i} ts: {a[4]} != {e[4]}"

    def test_row_count_matches_reference(self):
        """Row count must match independent WAL replay result."""
        expected_rows = _get_ref_rows()
        conn = sqlite3.connect(RECOVERED_PATH)
        count = conn.execute("SELECT COUNT(*) FROM sensors").fetchone()[0]
        conn.close()
        assert count == len(expected_rows), \
            f"Expected {len(expected_rows)} rows, got {count}"

    def test_corrupted_tx_deletions_not_applied(self):
        """Rows deleted in the corrupted transaction must still exist."""
        expected_rows = _get_ref_rows()
        expected_ids = {r[0] for r in expected_rows}
        conn = sqlite3.connect(RECOVERED_PATH)
        actual_ids = {r[0] for r in conn.execute("SELECT id FROM sensors").fetchall()}
        conn.close()
        assert actual_ids == expected_ids, \
            f"ID mismatch: expected {expected_ids}, got {actual_ids}"

    def test_corrupted_tx_insertions_not_applied(self):
        """Rows inserted in the corrupted transaction must not exist."""
        expected_rows = _get_ref_rows()
        max_expected_id = max(r[0] for r in expected_rows)
        conn = sqlite3.connect(RECOVERED_PATH)
        above = conn.execute(
            "SELECT id FROM sensors WHERE id > ?", (max_expected_id,)
        ).fetchall()
        conn.close()
        assert len(above) == 0, \
            f"Found rows beyond expected max id {max_expected_id}: {above}"

    def test_corrupted_tx_updates_not_applied(self):
        """Values from corrupted transaction must not appear."""
        expected_rows = _get_ref_rows()
        expected_readings = {r[0]: r[3] for r in expected_rows}
        conn = sqlite3.connect(RECOVERED_PATH)
        actual = conn.execute("SELECT id, reading FROM sensors").fetchall()
        conn.close()
        for row_id, reading in actual:
            expected = expected_readings.get(row_id)
            assert expected is not None, f"Unexpected row id {row_id}"
            assert abs(reading - expected) < 1e-10, \
                f"Row {row_id} reading: expected {expected}, got {reading}"


# ---------------------------------------------------------------------------
# Litestream configuration setup
# ---------------------------------------------------------------------------
class TestLitestreamSetup:
    def test_litestream_config_exists(self):
        assert os.path.isfile(LITESTREAM_CONFIG), \
            "Litestream config not found at /app/litestream.yml"

    def test_litestream_config_has_database_path(self):
        with open(LITESTREAM_CONFIG) as f:
            content = f.read()
        assert '/app/data/' in content, \
            "Config must reference database under /app/data/"

    def test_litestream_config_has_replica(self):
        with open(LITESTREAM_CONFIG) as f:
            content = f.read()
        assert 'replica' in content.lower(), \
            "Config must define replica configuration"
        assert 'replica' in content or 'replicas' in content, \
            "Config must contain replica or replicas field"

    def test_litestream_config_references_replica_path(self):
        with open(LITESTREAM_CONFIG) as f:
            content = f.read()
        assert '/app/data/replica' in content, \
            "Config must reference /app/data/replica as replica path"

    def test_validation_script_exists(self):
        assert os.path.isfile(VALIDATION_SCRIPT), \
            "Validation script not found at /app/validate_replication.sh"


# ---------------------------------------------------------------------------
# Litestream replication results
# ---------------------------------------------------------------------------
class TestLitestreamReplication:
    def test_replica_directory_exists(self):
        assert os.path.isdir(REPLICA_DIR), \
            "Replica directory not found at /app/data/replica"

    def test_replica_has_generations(self):
        """Litestream creates a generations/ subdirectory with hex-named entries."""
        gen_path = os.path.join(REPLICA_DIR, 'generations')
        assert os.path.isdir(gen_path), \
            "No generations/ directory in replica — Litestream may not have run"
        entries = os.listdir(gen_path)
        assert len(entries) > 0, "No generations found in replica"

    def test_replica_generation_has_snapshots(self):
        """Each generation should have a snapshots/ subdirectory."""
        gen_path = os.path.join(REPLICA_DIR, 'generations')
        if not os.path.isdir(gen_path):
            pytest.fail("No generations/ directory")
        entries = os.listdir(gen_path)
        if not entries:
            pytest.fail("No generations found")
        # Check first generation for snapshots
        first_gen = os.path.join(gen_path, entries[0])
        snapshot_path = os.path.join(first_gen, 'snapshots')
        assert os.path.isdir(snapshot_path), \
            f"No snapshots/ in generation {entries[0]}"
        snapshots = os.listdir(snapshot_path)
        assert len(snapshots) > 0, "No snapshot files found"

    def test_restored_db_exists(self):
        assert os.path.isfile(RESTORED_PATH), \
            "Restored database not found at /app/data/replica_restored.db"

    def test_restored_db_integrity(self):
        conn = sqlite3.connect(RESTORED_PATH)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        assert result[0] == 'ok', \
            f"Restored DB integrity check failed: {result}"

    def test_restored_db_has_sensors_table(self):
        conn = sqlite3.connect(RESTORED_PATH)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        assert 'sensors' in [t[0] for t in tables], \
            "Restored DB missing sensors table"

    def test_restored_db_has_original_sensor_data(self):
        """Restored database must contain the sensor data from WAL recovery."""
        ref_rows = _get_ref_rows()
        ref_ids = sorted({r[0] for r in ref_rows})
        conn = sqlite3.connect(RESTORED_PATH)
        placeholders = ','.join('?' for _ in ref_ids)
        rows = conn.execute(
            f"SELECT * FROM sensors WHERE id IN ({placeholders}) ORDER BY id",
            ref_ids
        ).fetchall()
        conn.close()

        assert len(rows) == len(ref_rows), \
            f"Expected {len(ref_rows)} original sensor rows, got {len(rows)}"
        for actual, expected in zip(rows, ref_rows):
            a, e = list(actual), list(expected)
            assert a[0] == e[0], f"ID mismatch: {a[0]} vs {e[0]}"
            assert a[1] == e[1], f"Name mismatch for id {a[0]}"
            assert abs(a[3] - e[3]) < 1e-10, \
                f"Reading mismatch for id {a[0]}: {a[3]} vs {e[3]}"

    def test_restored_db_has_more_rows_than_original(self):
        """Validation records should make restored DB have more rows."""
        ref_rows = _get_ref_rows()
        conn = sqlite3.connect(RESTORED_PATH)
        count = conn.execute("SELECT COUNT(*) FROM sensors").fetchone()[0]
        conn.close()
        assert count > len(ref_rows), \
            f"Restored DB should have validation rows beyond the " \
            f"{len(ref_rows)} original rows, but has {count}"

    def test_replication_report_exists(self):
        assert os.path.isfile(REPLICATION_REPORT), \
            "Replication report not found"

    def test_replication_report_structure(self):
        with open(REPLICATION_REPORT) as f:
            report = json.load(f)
        required_keys = [
            'litestream_version', 'replica_path', 'source_row_count',
            'validation_rows_inserted', 'restored_row_count',
            'data_consistent', 'integrity_check'
        ]
        for key in required_keys:
            assert key in report, f"Missing key in replication report: {key}"

    def test_replication_report_consistent(self):
        with open(REPLICATION_REPORT) as f:
            report = json.load(f)
        assert report.get('data_consistent') is True, \
            "Replication report indicates data inconsistency"
        assert report.get('integrity_check') == 'ok', \
            "Replication report integrity check not ok"

    def test_replication_report_row_counts(self):
        with open(REPLICATION_REPORT) as f:
            report = json.load(f)
        assert report.get('source_row_count', 0) > 0, \
            "Source row count should be positive"
        assert report.get('validation_rows_inserted', 0) > 0, \
            "Validation rows should have been inserted"
        assert report.get('restored_row_count', 0) >= \
            report.get('source_row_count', 0), \
            "Restored row count should be >= source row count"
