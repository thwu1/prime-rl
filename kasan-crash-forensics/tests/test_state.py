
"""
Outcome-based tests for the KASAN crash triage engine.
Verifies SQLite database content and JSON triage report correctness.
"""

import pytest
import sqlite3
import json
import os


def parse_addr(val):
    """Parse an address stored as hex string or signed/unsigned integer."""
    if val is None:
        return None
    if isinstance(val, int):
        return val + 2**64 if val < 0 else val
    s = str(val).strip().lower().replace('0x', '')
    return int(s, 16)


@pytest.fixture(scope='module')
def db():
    conn = sqlite3.connect('/app/triage.db')
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(scope='module')
def triage_report():
    with open('/app/triage_report.json') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Output existence
# ---------------------------------------------------------------------------

class TestOutputsExist:
    def test_db_exists(self):
        assert os.path.exists('/app/triage.db'), "triage.db not found"

    def test_report_exists(self):
        assert os.path.exists('/app/triage_report.json'), "triage_report.json not found"


# ---------------------------------------------------------------------------
# Database schema and row counts
# ---------------------------------------------------------------------------

class TestDatabaseSchema:
    def test_crashes_table(self, db):
        cur = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='crashes'")
        assert cur.fetchone() is not None

    def test_patch_verdicts_table(self, db):
        cur = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='patch_verdicts'")
        assert cur.fetchone() is not None

    def test_correlations_table(self, db):
        cur = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='correlations'")
        assert cur.fetchone() is not None

    def test_crash_count(self, db):
        assert db.execute("SELECT COUNT(*) FROM crashes").fetchone()[0] == 3

    def test_verdict_count(self, db):
        assert db.execute("SELECT COUNT(*) FROM patch_verdicts").fetchone()[0] == 3

    def test_correlation_count(self, db):
        assert db.execute("SELECT COUNT(*) FROM correlations").fetchone()[0] == 9


# ---------------------------------------------------------------------------
# Crash report 001 — slab-out-of-bounds
# ---------------------------------------------------------------------------

class TestCrashOOB:
    @pytest.fixture(autouse=True)
    def load(self, db):
        self.r = dict(db.execute(
            "SELECT * FROM crashes WHERE report_file='report_001.txt'"
        ).fetchone())

    def test_bug_type(self):
        assert self.r['bug_type'] == 'slab-out-of-bounds'

    def test_access_type(self):
        assert self.r['access_type'] == 'Read'

    def test_access_size(self):
        assert self.r['access_size'] == 2

    def test_faulting_function(self):
        assert self.r['faulting_function'] == 'nla_parse_nested_deprecated'

    def test_faulting_file(self):
        assert self.r['faulting_file'] == 'lib/nlattr.c'

    def test_faulting_line(self):
        assert self.r['faulting_line'] == 982

    def test_pid(self):
        assert self.r['pid'] == 8147

    def test_comm(self):
        assert self.r['comm'] == 'syz-executor.3'

    def test_slab_cache(self):
        assert self.r['slab_cache'] == 'kmalloc-32'

    def test_object_size(self):
        assert self.r['object_size'] == 32

    def test_buggy_addr(self):
        assert parse_addr(self.r['buggy_addr']) == 0xffff88803a1c4e62

    def test_object_addr(self):
        assert parse_addr(self.r['object_addr']) == 0xffff88803a1c4e40


# ---------------------------------------------------------------------------
# Crash report 002 — slab-use-after-free
# ---------------------------------------------------------------------------

class TestCrashUAF:
    @pytest.fixture(autouse=True)
    def load(self, db):
        self.r = dict(db.execute(
            "SELECT * FROM crashes WHERE report_file='report_002.txt'"
        ).fetchone())

    def test_bug_type(self):
        assert self.r['bug_type'] == 'slab-use-after-free'

    def test_access_type(self):
        assert self.r['access_type'] == 'Read'

    def test_access_size(self):
        assert self.r['access_size'] == 8

    def test_faulting_function(self):
        assert self.r['faulting_function'] == 'sk_filter_trim_cap'

    def test_faulting_file(self):
        assert self.r['faulting_file'] == 'net/core/filter.c'

    def test_slab_cache(self):
        assert self.r['slab_cache'] == 'kmalloc-64'

    def test_object_size(self):
        assert self.r['object_size'] == 64

    def test_buggy_addr(self):
        assert parse_addr(self.r['buggy_addr']) == 0xffff888054e21a00


# ---------------------------------------------------------------------------
# Crash report 003 — null-ptr-deref
# ---------------------------------------------------------------------------

class TestCrashNPD:
    @pytest.fixture(autouse=True)
    def load(self, db):
        self.r = dict(db.execute(
            "SELECT * FROM crashes WHERE report_file='report_003.txt'"
        ).fetchone())

    def test_bug_type(self):
        assert self.r['bug_type'] == 'null-ptr-deref'

    def test_access_type(self):
        assert self.r['access_type'] == 'Write'

    def test_access_size(self):
        assert self.r['access_size'] == 4

    def test_faulting_function(self):
        assert self.r['faulting_function'] == 'ext4_xattr_set_entry'

    def test_buggy_addr(self):
        assert parse_addr(self.r['buggy_addr']) == 0x28

    def test_no_slab_cache(self):
        assert self.r['slab_cache'] is None

    def test_no_object_size(self):
        assert self.r['object_size'] is None

    def test_no_shadow_start(self):
        assert self.r['shadow_object_start'] is None

    def test_no_shadow_freed(self):
        assert self.r['shadow_is_freed'] is None


# ---------------------------------------------------------------------------
# Shadow memory analysis — OOB
# ---------------------------------------------------------------------------

class TestShadowOOB:
    @pytest.fixture(autouse=True)
    def load(self, db):
        self.r = dict(db.execute(
            "SELECT shadow_object_start, shadow_object_size, "
            "shadow_is_freed, shadow_oob_distance "
            "FROM crashes WHERE report_file='report_001.txt'"
        ).fetchone())

    def test_object_start(self):
        assert parse_addr(self.r['shadow_object_start']) == 0xffff88803a1c4e40

    def test_object_size(self):
        assert self.r['shadow_object_size'] == 32

    def test_not_freed(self):
        assert self.r['shadow_is_freed'] == 0

    def test_oob_distance(self):
        assert self.r['shadow_oob_distance'] == 2


# ---------------------------------------------------------------------------
# Shadow memory analysis — UAF
# ---------------------------------------------------------------------------

class TestShadowUAF:
    @pytest.fixture(autouse=True)
    def load(self, db):
        self.r = dict(db.execute(
            "SELECT shadow_object_start, shadow_object_size, "
            "shadow_is_freed, shadow_oob_distance "
            "FROM crashes WHERE report_file='report_002.txt'"
        ).fetchone())

    def test_object_start(self):
        assert parse_addr(self.r['shadow_object_start']) == 0xffff888054e21a00

    def test_object_size(self):
        assert self.r['shadow_object_size'] == 64

    def test_is_freed(self):
        assert self.r['shadow_is_freed'] == 1

    def test_oob_distance(self):
        assert self.r['shadow_oob_distance'] == 0


# ---------------------------------------------------------------------------
# Patch verdicts from multi-VM results
# ---------------------------------------------------------------------------

class TestPatchVerdicts:
    def test_patch_001_pass(self, db):
        row = db.execute(
            "SELECT verdict, confidence FROM patch_verdicts "
            "WHERE patch_file='patch_001.diff'"
        ).fetchone()
        assert row['verdict'] == 'Pass'
        assert abs(row['confidence'] - 1.0) < 0.05

    def test_patch_002_racey(self, db):
        row = db.execute(
            "SELECT verdict, confidence FROM patch_verdicts "
            "WHERE patch_file='patch_002.diff'"
        ).fetchone()
        assert row['verdict'] == 'Racey'
        assert 0.0 < row['confidence'] <= 1.0

    def test_patch_003_trigger(self, db):
        row = db.execute(
            "SELECT verdict, confidence FROM patch_verdicts "
            "WHERE patch_file='patch_003.diff'"
        ).fetchone()
        assert row['verdict'] == 'Trigger'
        assert abs(row['confidence'] - 1.0) < 0.05


# ---------------------------------------------------------------------------
# Patch-crash correlations
# ---------------------------------------------------------------------------

class TestCorrelations:
    def _corr(self, db, report_file, patch_file):
        return dict(db.execute("""
            SELECT c.touches_faulting_function, c.file_overlap,
                   c.plausibility_score
            FROM correlations c
            JOIN crashes cr ON c.crash_id = cr.id
            JOIN patch_verdicts pv ON c.patch_id = pv.id
            WHERE cr.report_file = ? AND pv.patch_file = ?
        """, (report_file, patch_file)).fetchone())

    def test_patch001_crash001_touches_faulting(self, db):
        c = self._corr(db, 'report_001.txt', 'patch_001.diff')
        assert c['touches_faulting_function'] == 1

    def test_patch001_crash001_file_overlap(self, db):
        c = self._corr(db, 'report_001.txt', 'patch_001.diff')
        overlap = json.loads(c['file_overlap'])
        assert 'lib/nlattr.c' in overlap

    def test_patch001_crash001_plausibility(self, db):
        c = self._corr(db, 'report_001.txt', 'patch_001.diff')
        assert c['plausibility_score'] >= 0.5

    def test_patch003_crash003_touches_faulting(self, db):
        c = self._corr(db, 'report_003.txt', 'patch_003.diff')
        assert c['touches_faulting_function'] == 1

    def test_patch003_crash003_file_overlap(self, db):
        c = self._corr(db, 'report_003.txt', 'patch_003.diff')
        overlap = json.loads(c['file_overlap'])
        assert 'fs/ext4/xattr.c' in overlap

    def test_patch003_crash003_plausibility(self, db):
        c = self._corr(db, 'report_003.txt', 'patch_003.diff')
        assert c['plausibility_score'] >= 0.5

    def test_patch001_crash003_no_match(self, db):
        c = self._corr(db, 'report_003.txt', 'patch_001.diff')
        assert c['touches_faulting_function'] == 0
        assert c['plausibility_score'] <= 0.3

    def test_patch003_crash001_no_match(self, db):
        c = self._corr(db, 'report_001.txt', 'patch_003.diff')
        assert c['touches_faulting_function'] == 0
        assert c['plausibility_score'] <= 0.3

    def test_patch002_crash002_partial(self, db):
        c = self._corr(db, 'report_002.txt', 'patch_002.diff')
        assert c['touches_faulting_function'] == 0
        assert c['plausibility_score'] > 0.0


# ---------------------------------------------------------------------------
# JSON triage report
# ---------------------------------------------------------------------------

class TestTriageReport:
    def test_is_list(self, triage_report):
        assert isinstance(triage_report, list)

    def test_entry_count(self, triage_report):
        assert len(triage_report) == 3

    def test_required_fields(self, triage_report):
        for entry in triage_report:
            for key in ('crash_id', 'report_file', 'bug_type',
                        'faulting_function', 'recommended_patches'):
                assert key in entry, f"Missing field: {key}"

    def test_oob_shadow_analysis(self, triage_report):
        oob = next(e for e in triage_report
                   if e['bug_type'] == 'slab-out-of-bounds')
        sa = oob.get('shadow_analysis')
        assert sa is not None
        assert parse_addr(sa['object_start']) == 0xffff88803a1c4e40
        assert sa['object_size'] == 32
        assert sa['oob_distance'] == 2

    def test_uaf_shadow_analysis(self, triage_report):
        uaf = next(e for e in triage_report
                   if e['bug_type'] == 'slab-use-after-free')
        sa = uaf.get('shadow_analysis')
        assert sa is not None
        assert parse_addr(sa['object_start']) == 0xffff888054e21a00
        assert sa['object_size'] == 64
        assert sa['is_freed'] in (True, 1)

    def test_npd_no_shadow(self, triage_report):
        npd = next(e for e in triage_report
                   if e['bug_type'] == 'null-ptr-deref')
        assert npd.get('shadow_analysis') is None

    def test_patches_sorted_descending(self, triage_report):
        for entry in triage_report:
            scores = [p['plausibility_score']
                      for p in entry['recommended_patches']]
            assert scores == sorted(scores, reverse=True), \
                f"Patches not sorted by plausibility for {entry['report_file']}"

    def test_patch_entry_fields(self, triage_report):
        for entry in triage_report:
            for p in entry['recommended_patches']:
                for key in ('patch_file', 'verdict', 'confidence',
                            'plausibility_score'):
                    assert key in p, f"Missing patch field: {key}"
