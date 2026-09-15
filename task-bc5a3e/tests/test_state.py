
import pytest
import sqlite3
import json
import os


@pytest.fixture
def db():
    assert os.path.exists('/app/crash_triage.db'), \
        "Database /app/crash_triage.db does not exist"
    conn = sqlite3.connect('/app/crash_triage.db')
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def report():
    assert os.path.exists('/app/output/triage_report.json'), \
        "Report /app/output/triage_report.json does not exist"
    with open('/app/output/triage_report.json', 'r') as f:
        return json.load(f)


# ─── Database: crashes table ───────────────────────────────────────────


class TestCrashesTable:

    def test_crash_count(self, db):
        row = db.execute("SELECT count(*) as cnt FROM crashes").fetchone()
        assert row['cnt'] == 5

    def test_crash_001_kasan_uaf(self, db):
        r = db.execute("SELECT * FROM crashes WHERE id='crash_001'").fetchone()
        assert r is not None
        assert r['bug_type'] == 'slab-use-after-free'
        assert r['access_type'] == 'read'
        assert r['access_size'] == 8
        assert r['faulting_function'] == 'sock_release'
        assert r['task_comm'] == 'syz-executor.0'
        assert r['task_pid'] == 1234
        assert r['kernel_version'] == '6.1.0-rc5-syzkaller'

    def test_crash_001_call_trace(self, db):
        r = db.execute("SELECT call_trace_json FROM crashes WHERE id='crash_001'").fetchone()
        trace = json.loads(r['call_trace_json'])
        assert len(trace) == 8
        assert trace[0]['function'] == 'dump_stack_levels'
        assert trace[0]['offset'] == '0x1c'
        assert trace[0]['size'] == '0x30'
        assert trace[3]['function'] == 'sock_release'
        assert trace[3]['offset'] == '0x1c8'
        assert trace[3]['size'] == '0x200'
        assert trace[7]['function'] == 'kfree'

    def test_crash_002_kasan_oob(self, db):
        r = db.execute("SELECT * FROM crashes WHERE id='crash_002'").fetchone()
        assert r is not None
        assert r['bug_type'] == 'slab-out-of-bounds'
        assert r['access_type'] == 'write'
        assert r['access_size'] == 4
        assert r['faulting_function'] == 'ext4_getattr'
        assert r['task_comm'] == 'stat'
        assert r['task_pid'] == 5678
        assert r['kernel_version'] == '6.2.0-rc3'

    def test_crash_002_call_trace(self, db):
        r = db.execute("SELECT call_trace_json FROM crashes WHERE id='crash_002'").fetchone()
        trace = json.loads(r['call_trace_json'])
        assert len(trace) == 8
        assert trace[3]['function'] == 'ext4_getattr'
        assert trace[4]['function'] == 'ext4_inode_table'

    def test_crash_003_gpf(self, db):
        r = db.execute("SELECT * FROM crashes WHERE id='crash_003'").fetchone()
        assert r is not None
        assert r['bug_type'] == 'general-protection-fault'
        assert r['access_type'] is None
        assert r['access_size'] is None
        assert r['faulting_function'] == 'tcp_v4_rcv'
        assert r['task_comm'] == 'syz-executor.2'
        assert r['task_pid'] == 3456
        assert r['kernel_version'] == '6.3.0-syzkaller'

    def test_crash_003_call_trace(self, db):
        r = db.execute("SELECT call_trace_json FROM crashes WHERE id='crash_003'").fetchone()
        trace = json.loads(r['call_trace_json'])
        assert len(trace) == 5
        assert trace[0]['function'] == 'tcp_v4_rcv'
        assert trace[1]['function'] == 'ip_protocol_deliver_rcu'

    def test_crash_004_warning(self, db):
        r = db.execute("SELECT * FROM crashes WHERE id='crash_004'").fetchone()
        assert r is not None
        assert r['bug_type'] == 'warning'
        assert r['access_type'] is None
        assert r['access_size'] is None
        assert r['faulting_function'] == '__schedule'
        assert r['task_comm'] == 'kworker/1:3'
        assert r['task_pid'] == 7890
        assert r['kernel_version'] == '6.1.0-rc5'

    def test_crash_004_call_trace(self, db):
        r = db.execute("SELECT call_trace_json FROM crashes WHERE id='crash_004'").fetchone()
        trace = json.loads(r['call_trace_json'])
        assert len(trace) == 5
        assert trace[0]['function'] == '__schedule'
        assert trace[4]['function'] == 'hrtimer_nanosleep'

    def test_crash_005_kasan_uaf_variant(self, db):
        r = db.execute("SELECT * FROM crashes WHERE id='crash_005'").fetchone()
        assert r is not None
        assert r['bug_type'] == 'slab-use-after-free'
        assert r['access_type'] == 'read'
        assert r['access_size'] == 4
        assert r['faulting_function'] == 'sock_release'
        assert r['task_comm'] == 'syz-executor.3'
        assert r['task_pid'] == 2345

    def test_crash_005_call_trace(self, db):
        r = db.execute("SELECT call_trace_json FROM crashes WHERE id='crash_005'").fetchone()
        trace = json.loads(r['call_trace_json'])
        assert len(trace) == 8
        assert trace[7]['function'] == 'sk_clone_lock'


# ─── Database: dedup_groups table ──────────────────────────────────────


class TestDedupGroups:

    def _load_groups(self, db):
        rows = db.execute(
            "SELECT group_id, crash_id FROM dedup_groups "
            "ORDER BY group_id, crash_id"
        ).fetchall()
        groups = {}
        for row in rows:
            gid = row['group_id']
            if gid not in groups:
                groups[gid] = []
            groups[gid].append(row['crash_id'])
        return sorted(groups.values(), key=lambda g: g[0])

    def test_four_groups(self, db):
        groups = self._load_groups(db)
        assert len(groups) == 4

    def test_similar_crashes_grouped(self, db):
        groups = self._load_groups(db)
        found = False
        for g in groups:
            if 'crash_001' in g and 'crash_005' in g:
                found = True
                assert len(g) == 2
        assert found, "crash_001 and crash_005 must be in the same group"

    def test_singletons(self, db):
        groups = self._load_groups(db)
        singletons = sorted([g[0] for g in groups if len(g) == 1])
        assert singletons == ['crash_002', 'crash_003', 'crash_004']


# ─── Database: evaluations table ───────────────────────────────────────


class TestEvaluations:

    def test_resolved_bugs(self, db):
        rows = db.execute(
            "SELECT bug_id FROM evaluations WHERE status='resolved' "
            "ORDER BY bug_id"
        ).fetchall()
        assert [r['bug_id'] for r in rows] == ['net_sock_uaf__0', 'tcp_gpf__0']

    def test_unresolved_bugs(self, db):
        rows = db.execute(
            "SELECT bug_id FROM evaluations WHERE status='unresolved' "
            "ORDER BY bug_id"
        ).fetchall()
        assert [r['bug_id'] for r in rows] == ['net_clone_uaf__0']

    def test_resolved_trial_counts(self, db):
        r = db.execute(
            "SELECT total_clean_runs, total_trials FROM evaluations "
            "WHERE bug_id='net_sock_uaf__0'"
        ).fetchone()
        assert r['total_clean_runs'] == 3
        assert r['total_trials'] == 3

    def test_unresolved_trial_counts(self, db):
        r = db.execute(
            "SELECT total_clean_runs, total_trials FROM evaluations "
            "WHERE bug_id='net_clone_uaf__0'"
        ).fetchone()
        assert r['total_clean_runs'] == 1
        assert r['total_trials'] == 2

    def test_evaluation_count(self, db):
        row = db.execute("SELECT count(*) as cnt FROM evaluations").fetchone()
        assert row['cnt'] == 3


# ─── JSON report: crash_groups ─────────────────────────────────────────


class TestReportCrashGroups:

    def test_group_count(self, report):
        assert len(report['crash_groups']) == 4

    def test_similar_grouped(self, report):
        found = False
        for g in report['crash_groups']:
            if 'crash_001' in g and 'crash_005' in g:
                found = True
                assert g == ['crash_001', 'crash_005']
        assert found

    def test_singletons(self, report):
        singletons = sorted([g[0] for g in report['crash_groups'] if len(g) == 1])
        assert singletons == ['crash_002', 'crash_003', 'crash_004']

    def test_outer_sorted(self, report):
        first_elems = [g[0] for g in report['crash_groups']]
        assert first_elems == sorted(first_elems)


# ─── JSON report: evaluation ──────────────────────────────────────────


class TestReportEvaluation:

    def test_resolved(self, report):
        assert sorted(report['evaluation']['resolved']) == \
            ['net_sock_uaf__0', 'tcp_gpf__0']

    def test_unresolved(self, report):
        assert report['evaluation']['unresolved'] == ['net_clone_uaf__0']

    def test_resolution_count(self, report):
        assert report['evaluation']['resolution_count'] == 2


# ─── JSON report: localization ─────────────────────────────────────────


class TestReportLocalization:

    def test_precision_at_1(self, report):
        assert report['localization']['precision_at_1'] == pytest.approx(1.0)

    def test_recall_at_1(self, report):
        assert report['localization']['recall_at_1'] == pytest.approx(0.5)

    def test_precision_at_3(self, report):
        assert report['localization']['precision_at_3'] == pytest.approx(2.0 / 3.0)

    def test_recall_at_3(self, report):
        assert report['localization']['recall_at_3'] == pytest.approx(1.0)

    def test_precision_at_5(self, report):
        assert report['localization']['precision_at_5'] == pytest.approx(0.4)

    def test_recall_at_5(self, report):
        assert report['localization']['recall_at_5'] == pytest.approx(1.0)

    def test_file_iou(self, report):
        assert report['localization']['file_iou'] == pytest.approx(0.4)
