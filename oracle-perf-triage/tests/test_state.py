
import json
import os
import re
import pytest


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_text(path):
    with open(path) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Output files exist
# ---------------------------------------------------------------------------

class TestOutputFilesExist:
    def test_metrics_json_exists(self):
        assert os.path.exists('/app/output/metrics.json'), \
            "metrics.json not found in /app/output/"

    def test_findings_json_exists(self):
        assert os.path.exists('/app/output/findings.json'), \
            "findings.json not found in /app/output/"

    def test_remediation_sql_exists(self):
        assert os.path.exists('/app/output/remediation.sql'), \
            "remediation.sql not found in /app/output/"

    def test_audit_report_exists(self):
        assert os.path.exists('/app/output/audit_report.json'), \
            "audit_report.json not found in /app/output/"


# ---------------------------------------------------------------------------
# Metrics accuracy
# ---------------------------------------------------------------------------

class TestMetrics:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.metrics = load_json('/app/output/metrics.json')

    def test_buffer_cache_hit_ratio(self):
        """Expected: 1 - (5421087 / (45283102 + 8917643)) ~ 0.8999"""
        ratio = self.metrics.get('buffer_cache_hit_ratio', -1)
        assert 0.895 <= ratio <= 0.905, \
            f"buffer_cache_hit_ratio {ratio} not in [0.895, 0.905]"

    def test_library_cache_hit_ratio(self):
        """Expected: 40945550 / 47195565 ~ 0.8676"""
        ratio = self.metrics.get('library_cache_hit_ratio', -1)
        assert 0.862 <= ratio <= 0.873, \
            f"library_cache_hit_ratio {ratio} not in [0.862, 0.873]"

    def test_soft_parse_ratio(self):
        """Expected: 1 - (2867412 / 8234567) ~ 0.6517"""
        ratio = self.metrics.get('soft_parse_ratio', -1)
        assert 0.645 <= ratio <= 0.658, \
            f"soft_parse_ratio {ratio} not in [0.645, 0.658]"

    def test_recommended_db_cache_size(self):
        """Advisory inflection point at 1024 MB. Accept 768-1536."""
        size = self.metrics.get('recommended_db_cache_size_mb', 0)
        assert 768 <= size <= 1536, \
            f"recommended_db_cache_size_mb {size} not in [768, 1536]"

    def test_recommended_pga_target(self):
        """Zero over-allocation at 1024 MB. Must recommend >= 1024."""
        size = self.metrics.get('recommended_pga_target_mb', 0)
        assert 1024 <= size <= 2048, \
            f"recommended_pga_target_mb {size} not in [1024, 2048]"


# ---------------------------------------------------------------------------
# Findings: must identify each major root cause
# ---------------------------------------------------------------------------

class TestFindings:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.findings = load_json('/app/output/findings.json')
        self.text = json.dumps(self.findings).lower()

    def test_identifies_buffer_cache_issue(self):
        assert any(t in self.text for t in [
            'buffer cache', 'buffer_cache', 'db_cache_size',
            'db file sequential read', 'physical read',
        ]), "Findings must identify buffer cache sizing issue"

    def test_identifies_hard_parsing(self):
        assert any(t in self.text for t in [
            'hard pars', 'cursor_sharing', 'cursor sharing',
            'library cache', 'literal sql', 'bind variable',
            'soft parse', 'shared pool',
        ]), "Findings must identify hard parsing / cursor sharing issue"

    def test_identifies_pga_issue(self):
        assert any(t in self.text for t in [
            'pga', 'pga_aggregate_target', 'over-alloc',
            'over_alloc', 'overalloc', 'multipass',
        ]), "Findings must identify PGA sizing issue"

    def test_identifies_segment_contention(self):
        assert any(t in self.text for t in [
            'buffer busy', 'contention', 'hot block', 'hot segment',
            'hot table', 'orders', 'itl', 'latch',
        ]), "Findings must identify segment contention issue"

    def test_identifies_problematic_sql(self):
        assert any(t in self.text for t in [
            'full scan', 'full table scan', 'hint', 'no_index',
            'missing index', 'status', 'execution plan',
            '4qr7st8u9v0w1', '3st4uv5w6x7y8', '8lm9no0p1q2r3',
        ]), "Findings must identify problematic SQL statements"


# ---------------------------------------------------------------------------
# Remediation SQL: correct Oracle commands
# ---------------------------------------------------------------------------

class TestRemediation:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.sql = load_text('/app/output/remediation.sql').lower()

    def test_sets_db_cache_size(self):
        assert 'db_cache_size' in self.sql, \
            "Remediation must ALTER SYSTEM SET db_cache_size"
        m = re.search(r'db_cache_size\s*=\s*[\'"]?(\d+)', self.sql)
        if m:
            val = int(m.group(1))
            assert val >= 768 or val >= 805306368, \
                f"db_cache_size value {val} too small (need >= 768 MB)"

    def test_sets_cursor_sharing_force(self):
        assert 'cursor_sharing' in self.sql, \
            "Remediation must ALTER SYSTEM SET cursor_sharing"
        assert 'force' in self.sql, \
            "cursor_sharing must be set to FORCE"

    def test_sets_pga_aggregate_target(self):
        assert 'pga_aggregate_target' in self.sql, \
            "Remediation must ALTER SYSTEM SET pga_aggregate_target"
        m = re.search(r'pga_aggregate_target\s*=\s*[\'"]?(\d+)', self.sql)
        if m:
            val = int(m.group(1))
            assert val >= 1024 or val >= 1073741824, \
                f"pga_aggregate_target value {val} too small (need >= 1024 MB)"

    def test_creates_index_on_status(self):
        assert 'create index' in self.sql or 'create  index' in self.sql, \
            "Remediation must CREATE INDEX"
        assert 'status' in self.sql, \
            "Must create index on STATUS column"
        assert 'orders' in self.sql, \
            "Must create index on ORDERS table"


# ---------------------------------------------------------------------------
# Audit report: evaluate prior analysis
# ---------------------------------------------------------------------------

class TestAuditReport:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.report = load_json('/app/output/audit_report.json')
        self.text = json.dumps(self.report).lower()

    def test_has_required_sections(self):
        assert 'prior_findings_assessment' in self.report, \
            "audit_report must contain prior_findings_assessment"
        assert 'missed_issues' in self.report, \
            "audit_report must contain missed_issues"
        assert 'data_anomalies' in self.report, \
            "audit_report must contain data_anomalies"

    def test_evaluates_all_prior_findings(self):
        assessments = self.report['prior_findings_assessment']
        assessment_text = json.dumps(assessments).upper()
        assert all(fid in assessment_text for fid in ['P1', 'P2', 'P3']), \
            "Must evaluate all three prior findings (P1, P2, P3)"

    def test_identifies_buffer_cache_calculation_error(self):
        """P1 used 'physical reads' instead of 'physical reads cache'."""
        assessments = self.report.get('prior_findings_assessment', [])
        found = False
        for a in assessments:
            a_text = json.dumps(a).lower()
            is_p1 = (str(a.get('finding_id', '')).upper() == 'P1' or
                     'buffer cache' in a_text or 'hit ratio' in a_text)
            has_critique = any(t in a_text for t in [
                'incorrect', 'wrong', 'error', 'partially_incorrect',
                'inaccurate', 'miscalcul', 'physical reads cache',
                'physical reads direct', 'direct path',
            ])
            if is_p1 and has_critique:
                found = True
                break
        assert found, \
            "Must identify calculation error in P1 buffer cache finding"

    def test_identifies_redo_misdiagnosis(self):
        """P2 redo contention is a false/exaggerated finding."""
        assessments = self.report.get('prior_findings_assessment', [])
        found = False
        for a in assessments:
            a_text = json.dumps(a).lower()
            is_p2 = (str(a.get('finding_id', '')).upper() == 'P2' or
                     'redo' in a_text or 'log file' in a_text)
            has_critique = any(t in a_text for t in [
                'incorrect', 'wrong', 'false', 'exaggerated', 'misleading',
                'overstat', 'misdiagnos', 'not critical', 'not significant',
                'normal', 'acceptable', 'not a bottleneck',
            ])
            if is_p2 and has_critique:
                found = True
                break
        assert found, \
            "Must identify P2 redo contention as incorrect/exaggerated"

    def test_identifies_pga_recommendation_insufficient(self):
        """P3 recommended 768 MB but over-alloc is still 412 there."""
        assessments = self.report.get('prior_findings_assessment', [])
        found = False
        for a in assessments:
            a_text = json.dumps(a).lower()
            is_p3 = (str(a.get('finding_id', '')).upper() == 'P3' or
                     'pga' in a_text)
            has_critique = any(t in a_text for t in [
                'insufficient', 'too small', 'too low', 'inadequate',
                'partially_incorrect', 'incorrect', '1024',
                'non-zero', 'over-alloc', 'overalloc', 'still',
            ])
            if is_p3 and has_critique:
                found = True
                break
        assert found, \
            "Must identify P3 PGA recommendation as insufficient"

    def test_identifies_missed_parsing_issue(self):
        missed = self.report.get('missed_issues', [])
        missed_text = json.dumps(missed).lower()
        assert any(t in missed_text for t in [
            'pars', 'cursor', 'literal', 'bind', 'shared pool', 'soft parse',
        ]), "Missed issues must include hard parsing / cursor sharing"

    def test_identifies_missed_contention(self):
        missed = self.report.get('missed_issues', [])
        missed_text = json.dumps(missed).lower()
        assert any(t in missed_text for t in [
            'contention', 'hot', 'orders', 'buffer busy', 'segment', 'itl',
        ]), "Missed issues must include segment contention"

    def test_identifies_data_quality_issues(self):
        anomalies = self.report.get('data_anomalies', [])
        anomaly_text = json.dumps(anomalies).lower()
        assert any(t in anomaly_text for t in [
            'corrupt', 'negative', 'duplicate', 'anomal', 'invalid',
            'trailing', 'spurious', 'bad data', 'data quality', 'inconsistent',
        ]), "Must detect data quality anomalies in source data"
