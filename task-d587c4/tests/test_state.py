#!/usr/bin/env python3
"""Tests for IR evaluation audit: cross-tool reconciliation.

Verifies that:
1. trec_eval is compiled and produces correct output
2. The custom evaluation script bugs are all fixed
3. Both tools agree on MRR@10 for all systems
4. SQLite database is populated with per-query scores from both tools
5. The audit report has correct structure and values
"""

import json
import os
import re
import sqlite3
import subprocess
import tempfile
import bz2
import pytest


# ---------------------------------------------------------------------------
# Helper functions: independent MRR@10 computation for cross-checking
# ---------------------------------------------------------------------------

def load_qrels(path):
    """Load qrels in TREC format: qid\\t0\\tpid\\trel (any rel > 0)."""
    qrels = {}
    with open(path, 'r') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 4:
                continue
            qid = int(parts[0])
            pid = int(parts[2])
            rel = int(parts[3])
            if rel > 0:
                if qid not in qrels:
                    qrels[qid] = []
                qrels[qid].append(pid)
    return qrels


def load_run_msmarco(path):
    """Load MS MARCO format run (optionally bz2): qid\\tpid\\trank"""
    opener = bz2.open if path.endswith('.bz2') else open
    mode = 'rt' if path.endswith('.bz2') else 'r'
    run = {}
    with opener(path, mode) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 3:
                continue
            qid = int(parts[0])
            pid = int(parts[1])
            rank = int(parts[2])
            if qid not in run:
                run[qid] = {}
            if pid not in run[qid] or rank < run[qid][pid]:
                run[qid][pid] = rank
    result = {}
    for qid in run:
        ranked = sorted(run[qid].items(), key=lambda x: x[1])
        result[qid] = [pid for pid, _ in ranked]
    return result


def load_run_trec(path):
    """Load TREC format run: qid\\tQ0\\tpid\\trank\\tscore\\trun_name"""
    run = {}
    with open(path, 'r') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 4:
                parts = line.strip().split()
            if len(parts) < 4:
                continue
            qid = int(parts[0])
            pid = int(parts[2])
            rank = int(parts[3])
            if qid not in run:
                run[qid] = {}
            if pid not in run[qid] or rank < run[qid][pid]:
                run[qid][pid] = rank
    result = {}
    for qid in run:
        ranked = sorted(run[qid].items(), key=lambda x: x[1])
        result[qid] = [pid for pid, _ in ranked]
    return result


def compute_mrr_at_10(qrels, run):
    """Compute MRR@10 independently."""
    mrr_sum = 0.0
    for qid in run:
        if qid in qrels:
            relevant = set(qrels[qid])
            ranked_pids = run[qid][:10]
            for i, pid in enumerate(ranked_pids):
                if pid in relevant:
                    mrr_sum += 1.0 / (i + 1)
                    break
    return mrr_sum / len(qrels)


def _parse_mrr_from_output(output):
    """Extract MRR value from custom eval script output."""
    match = re.search(r'MRR.*?:\s*([\d.]+)', output)
    assert match is not None, "Could not parse MRR from output: {}".format(output)
    return float(match.group(1))


def _parse_trec_eval_mrr(output):
    """Parse overall MRR from trec_eval output (recip_rank\\tall\\tvalue)."""
    for line in output.strip().split('\n'):
        parts = line.strip().split()
        if len(parts) >= 3 and parts[1] == 'all':
            return float(parts[2])
    raise ValueError("Could not find 'all' line in trec_eval output: {}".format(output))


# ---------------------------------------------------------------------------
# Test class: trec_eval compilation and basic functionality
# ---------------------------------------------------------------------------

class TestTrecEval:

    def test_binary_exists(self):
        """trec_eval binary must be compiled and executable."""
        assert os.path.exists('/app/trec_eval_src/trec_eval'), \
            "trec_eval binary not found at /app/trec_eval_src/trec_eval"
        assert os.access('/app/trec_eval_src/trec_eval', os.X_OK), \
            "trec_eval binary is not executable"

    def test_basic_reciprocal_rank(self):
        """trec_eval must compute correct recip_rank on simple input."""
        qf = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        qf.write("1 0 100 1\n")
        qf.close()
        rf = tempfile.NamedTemporaryFile(mode='w', suffix='.trec', delete=False)
        rf.write("1 Q0 100 1 1000.0 test\n1 Q0 999 2 500.0 test\n")
        rf.close()
        try:
            result = subprocess.run(
                ['/app/trec_eval_src/trec_eval', '-m', 'recip_rank.10',
                 qf.name, rf.name],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, "trec_eval failed: {}".format(result.stderr)
            mrr = _parse_trec_eval_mrr(result.stdout)
            assert abs(mrr - 1.0) < 1e-4, \
                "Expected MRR=1.0, got {}".format(mrr)
        finally:
            os.unlink(qf.name)
            os.unlink(rf.name)

    def test_rank_10_cutoff(self):
        """trec_eval must include rank 10 in recip_rank.10."""
        qf = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        qf.write("1 0 100 1\n")
        qf.close()
        rf = tempfile.NamedTemporaryFile(mode='w', suffix='.trec', delete=False)
        lines = []
        for r in range(1, 11):
            pid = 100 if r == 10 else 900 + r
            lines.append("1 Q0 {} {} {:.1f} test\n".format(pid, r, 1000.0 / r))
        rf.write("".join(lines))
        rf.close()
        try:
            result = subprocess.run(
                ['/app/trec_eval_src/trec_eval', '-m', 'recip_rank.10',
                 qf.name, rf.name],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, "trec_eval failed: {}".format(result.stderr)
            mrr = _parse_trec_eval_mrr(result.stdout)
            assert abs(mrr - 0.1) < 1e-4, \
                "Rank 10 should give MRR=0.1, got {}".format(mrr)
        finally:
            os.unlink(qf.name)
            os.unlink(rf.name)

    def test_electra_mrr(self):
        """trec_eval on ELECTRA run must match independent computation."""
        qrels = load_qrels('/app/data/qrels.txt')
        run = load_run_trec('/app/runs/electra.trec')
        expected = compute_mrr_at_10(qrels, run)
        result = subprocess.run(
            ['/app/trec_eval_src/trec_eval', '-m', 'recip_rank.10',
             '/app/data/qrels.txt', '/app/runs/electra.trec'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, "trec_eval failed: {}".format(result.stderr)
        actual = _parse_trec_eval_mrr(result.stdout)
        assert abs(actual - expected) < 1e-3, \
            "trec_eval MRR {} != expected {}".format(actual, expected)


# ---------------------------------------------------------------------------
# Test class: eval script bug fixes
# ---------------------------------------------------------------------------

class TestEvalScriptFixed:

    def test_eval_script_exists(self):
        assert os.path.exists('/app/eval/msmarco_eval.py')

    def test_maxmrrrank_is_10(self):
        """MaxMRRRank must be 10 for MRR@10."""
        with open('/app/eval/msmarco_eval.py', 'r') as f:
            content = f.read()
        assert re.search(r'MaxMRRRank\s*=\s*10\b', content), \
            "MaxMRRRank should be 10"

    def test_no_strict_rel_filter(self):
        """Eval script must not filter for rel==1 (must accept graded relevance)."""
        with open('/app/eval/msmarco_eval.py', 'r') as f:
            content = f.read()
        assert not re.search(r'int\(l\[3\]\)\s*==\s*1', content), \
            "Eval script has rel==1 filter that excludes graded relevance"

    def test_rank_indexing_correct(self):
        """Rank 1 passage must contribute reciprocal rank 1.0, not 0.5."""
        qrels_content = "1\t0\t100\t1\n"
        run_content = "1\t100\t1\n1\t999\t2\n"
        qf = tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False)
        qf.write(qrels_content)
        qf.close()
        rf = tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False)
        rf.write(run_content)
        rf.close()
        try:
            result = subprocess.run(
                ['python3', '/app/eval/msmarco_eval.py', qf.name, rf.name],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, "Eval script failed: {}".format(result.stderr)
            mrr = _parse_mrr_from_output(result.stdout)
            assert abs(mrr - 1.0) < 1e-6, \
                "Rank 1 passage should give MRR=1.0, got {}".format(mrr)
        finally:
            os.unlink(qf.name)
            os.unlink(rf.name)

    def test_rank_10_included(self):
        """Relevant passage at rank 10 must contribute 1/10 to MRR@10."""
        qrels_content = "1\t0\t100\t1\n"
        run_lines = []
        for r in range(1, 11):
            if r == 10:
                run_lines.append("1\t100\t{}\n".format(r))
            else:
                run_lines.append("1\t{}\t{}\n".format(900 + r, r))
        run_content = "".join(run_lines)
        qf = tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False)
        qf.write(qrels_content)
        qf.close()
        rf = tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False)
        rf.write(run_content)
        rf.close()
        try:
            result = subprocess.run(
                ['python3', '/app/eval/msmarco_eval.py', qf.name, rf.name],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, "Eval script failed: {}".format(result.stderr)
            mrr = _parse_mrr_from_output(result.stdout)
            assert abs(mrr - 0.1) < 1e-6, \
                "Rank 10 passage should give MRR=0.1, got {}".format(mrr)
        finally:
            os.unlink(qf.name)
            os.unlink(rf.name)

    def test_mrr_denominator_correct(self):
        """MRR must divide by judged queries, not ranked queries."""
        qrels_content = "1\t0\t100\t1\n2\t0\t200\t1\n"
        run_content = "1\t100\t1\n1\t999\t2\n2\t999\t1\n2\t200\t11\n3\t888\t1\n"
        qf = tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False)
        qf.write(qrels_content)
        qf.close()
        rf = tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False)
        rf.write(run_content)
        rf.close()
        try:
            result = subprocess.run(
                ['python3', '/app/eval/msmarco_eval.py', qf.name, rf.name],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, "Eval script failed: {}".format(result.stderr)
            mrr = _parse_mrr_from_output(result.stdout)
            assert abs(mrr - 0.5) < 1e-6, \
                "MRR should be 0.5 (2 judged queries), got {}".format(mrr)
        finally:
            os.unlink(qf.name)
            os.unlink(rf.name)

    def test_graded_relevance_handled(self):
        """Passages with relevance grade > 1 must be treated as relevant."""
        qrels_content = "1\t0\t100\t2\n2\t0\t200\t1\n"
        run_content = "1\t100\t1\n1\t999\t2\n2\t888\t1\n2\t200\t2\n"
        # Expected: query 1 RR=1.0 (pid 100 at rank 1), query 2 RR=0.5 (pid 200 at rank 2)
        # MRR = (1.0 + 0.5) / 2 = 0.75
        qf = tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False)
        qf.write(qrels_content)
        qf.close()
        rf = tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False)
        rf.write(run_content)
        rf.close()
        try:
            result = subprocess.run(
                ['python3', '/app/eval/msmarco_eval.py', qf.name, rf.name],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, "Eval script failed: {}".format(result.stderr)
            mrr = _parse_mrr_from_output(result.stdout)
            assert abs(mrr - 0.75) < 1e-6, \
                "MRR should be 0.75 with graded relevance, got {}".format(mrr)
        finally:
            os.unlink(qf.name)
            os.unlink(rf.name)

    def test_eval_script_correct_mrr_bm25(self):
        """Fixed eval script must match independently computed MRR on BM25 run."""
        qrels = load_qrels('/app/data/qrels.txt')
        run = load_run_msmarco('/app/runs/bm25.tsv')
        expected_mrr = compute_mrr_at_10(qrels, run)
        result = subprocess.run(
            ['python3', '/app/eval/msmarco_eval.py',
             '/app/data/qrels.txt', '/app/runs/bm25.tsv'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, "Eval script failed: {}".format(result.stderr)
        actual_mrr = _parse_mrr_from_output(result.stdout)
        assert abs(actual_mrr - expected_mrr) < 1e-6, \
            "Eval MRR {} != expected {}".format(actual_mrr, expected_mrr)


# ---------------------------------------------------------------------------
# Test class: cross-tool validation
# ---------------------------------------------------------------------------

class TestCrossToolValidation:

    def test_cross_tool_section_exists(self):
        """Audit report must have cross_tool_validation section."""
        assert os.path.exists('/app/output/audit_report.json'), \
            "audit_report.json not found"
        with open('/app/output/audit_report.json', 'r') as f:
            report = json.load(f)
        assert 'cross_tool_validation' in report, \
            "Missing 'cross_tool_validation' key in audit report"

    def test_all_systems_match(self):
        """Custom eval and trec_eval must agree on MRR@10 for all systems."""
        with open('/app/output/audit_report.json', 'r') as f:
            report = json.load(f)
        for entry in report['cross_tool_validation']:
            assert entry['match'], \
                "Tool mismatch for {}: custom={}, trec_eval={}".format(
                    entry['system'], entry['custom_mrr'], entry['trec_eval_mrr'])

    def test_cross_tool_covers_all_systems(self):
        """cross_tool_validation must cover all 4 systems."""
        with open('/app/output/audit_report.json', 'r') as f:
            report = json.load(f)
        systems = {e['system'] for e in report['cross_tool_validation']}
        expected = {'bm25', 'tfidf', 'knrm', 'electra'}
        assert systems == expected, \
            "cross_tool systems {} != expected {}".format(systems, expected)

    def test_cross_tool_mrr_values_correct(self):
        """cross_tool_validation MRR values must match independent computation."""
        qrels = load_qrels('/app/data/qrels.txt')
        runs = {
            'bm25': load_run_msmarco('/app/runs/bm25.tsv'),
            'tfidf': load_run_msmarco('/app/runs/tfidf.tsv'),
            'knrm': load_run_msmarco('/app/runs/knrm.txt.bz2'),
            'electra': load_run_trec('/app/runs/electra.trec'),
        }
        expected_mrrs = {name: compute_mrr_at_10(qrels, run)
                         for name, run in runs.items()}
        with open('/app/output/audit_report.json', 'r') as f:
            report = json.load(f)
        for entry in report['cross_tool_validation']:
            name = entry['system']
            expected = expected_mrrs[name]
            assert abs(entry['custom_mrr'] - expected) < 1e-4, \
                "{} custom_mrr {} != expected {}".format(name, entry['custom_mrr'], expected)
            assert abs(entry['trec_eval_mrr'] - expected) < 1e-3, \
                "{} trec_eval_mrr {} != expected {}".format(name, entry['trec_eval_mrr'], expected)


# ---------------------------------------------------------------------------
# Test class: SQLite database population
# ---------------------------------------------------------------------------

class TestSQLitePopulated:

    def test_database_exists(self):
        """results.db must exist."""
        assert os.path.exists('/app/results.db'), "results.db not found"

    def test_per_query_has_both_tools(self):
        """per_query_scores must have entries from both 'custom' and 'trec_eval'."""
        db = sqlite3.connect('/app/results.db')
        tools = db.execute(
            "SELECT DISTINCT tool FROM per_query_scores"
        ).fetchall()
        tool_set = {t[0] for t in tools}
        db.close()
        assert 'custom' in tool_set, "No 'custom' entries in per_query_scores"
        assert 'trec_eval' in tool_set, "No 'trec_eval' entries in per_query_scores"

    def test_per_query_has_all_systems(self):
        """per_query_scores must have entries for all 4 systems from both tools."""
        db = sqlite3.connect('/app/results.db')
        rows = db.execute(
            "SELECT DISTINCT system_name, tool FROM per_query_scores ORDER BY system_name, tool"
        ).fetchall()
        db.close()
        combos = {(r[0], r[1]) for r in rows}
        expected_systems = {'bm25', 'tfidf', 'knrm', 'electra'}
        expected_tools = {'custom', 'trec_eval'}
        for sys in expected_systems:
            for tool in expected_tools:
                assert (sys, tool) in combos, \
                    "Missing ({}, {}) in per_query_scores".format(sys, tool)

    def test_per_query_count(self):
        """Each system-tool combination must have scores for judged queries."""
        db = sqlite3.connect('/app/results.db')
        row = db.execute(
            "SELECT MIN(cnt) FROM (SELECT COUNT(*) as cnt FROM per_query_scores "
            "GROUP BY system_name, tool)"
        ).fetchone()
        db.close()
        assert row[0] >= 100, \
            "Too few per-query scores: min count = {}".format(row[0])

    def test_summary_populated(self):
        """summary table must have mean scores from both tools."""
        db = sqlite3.connect('/app/results.db')
        row = db.execute("SELECT COUNT(*) FROM summary").fetchone()
        db.close()
        assert row[0] >= 8, \
            "Expected at least 8 summary rows (4 systems x 2 tools), got {}".format(row[0])


# ---------------------------------------------------------------------------
# Test class: audit report structure and values
# ---------------------------------------------------------------------------

class TestAuditReport:

    def test_report_exists(self):
        assert os.path.exists('/app/output/audit_report.json'), \
            "audit_report.json not found"

    def test_report_structure(self):
        with open('/app/output/audit_report.json', 'r') as f:
            report = json.load(f)
        assert 'systems' in report, "Missing 'systems' key"
        assert 'pairwise_significance' in report, "Missing 'pairwise_significance' key"
        assert 'cross_tool_validation' in report, "Missing 'cross_tool_validation' key"
        assert len(report['systems']) == 4, \
            "Expected 4 systems, got {}".format(len(report['systems']))

    def test_system_fields(self):
        with open('/app/output/audit_report.json', 'r') as f:
            report = json.load(f)
        required = {'name', 'mrr_at_10', 'queries_ranked', 'ci_95_lower', 'ci_95_upper'}
        for system in report['systems']:
            for field in required:
                assert field in system, \
                    "System {} missing field '{}'".format(system.get('name', '?'), field)

    def test_system_names(self):
        with open('/app/output/audit_report.json', 'r') as f:
            report = json.load(f)
        names = {s['name'] for s in report['systems']}
        expected = {'bm25', 'tfidf', 'knrm', 'electra'}
        assert names == expected, "System names {} != expected {}".format(names, expected)

    def test_mrr_values(self):
        """MRR@10 values must match independent computation."""
        qrels = load_qrels('/app/data/qrels.txt')
        runs = {
            'bm25': load_run_msmarco('/app/runs/bm25.tsv'),
            'tfidf': load_run_msmarco('/app/runs/tfidf.tsv'),
            'knrm': load_run_msmarco('/app/runs/knrm.txt.bz2'),
            'electra': load_run_trec('/app/runs/electra.trec'),
        }
        expected_mrrs = {name: compute_mrr_at_10(qrels, run)
                         for name, run in runs.items()}
        with open('/app/output/audit_report.json', 'r') as f:
            report = json.load(f)
        for system in report['systems']:
            name = system['name']
            expected = expected_mrrs[name]
            actual = system['mrr_at_10']
            assert abs(actual - expected) < 1e-4, \
                "System {}: MRR {} != expected {}".format(name, actual, expected)

    def test_ordering(self):
        """Systems must be sorted by MRR@10 descending."""
        with open('/app/output/audit_report.json', 'r') as f:
            report = json.load(f)
        mrrs = [s['mrr_at_10'] for s in report['systems']]
        assert mrrs == sorted(mrrs, reverse=True), \
            "Systems not sorted by MRR@10 descending"

    def test_confidence_intervals(self):
        """Bootstrap CIs must contain the point estimate and have reasonable width."""
        with open('/app/output/audit_report.json', 'r') as f:
            report = json.load(f)
        for system in report['systems']:
            mrr = system['mrr_at_10']
            lower = system['ci_95_lower']
            upper = system['ci_95_upper']
            assert lower < mrr < upper, \
                "System {}: CI [{}, {}] doesn't contain MRR {}".format(
                    system['name'], lower, upper, mrr)
            width = upper - lower
            assert width < 0.2, \
                "System {}: CI width {} too large".format(system['name'], width)
            assert width > 0.001, \
                "System {}: CI width {} suspiciously small".format(system['name'], width)

    def test_pairwise_significance_structure(self):
        """Must have 6 pairwise comparisons with required fields."""
        with open('/app/output/audit_report.json', 'r') as f:
            report = json.load(f)
        pairs = report['pairwise_significance']
        assert len(pairs) == 6, \
            "Expected 6 pairwise comparisons, got {}".format(len(pairs))
        required = {'system_a', 'system_b', 'delta_mrr', 'p_value', 'significant_at_005'}
        for pair in pairs:
            for field in required:
                assert field in pair, "Pair missing field '{}'".format(field)
            assert 0 <= pair['p_value'] <= 1, \
                "Invalid p_value: {}".format(pair['p_value'])
            assert isinstance(pair['significant_at_005'], bool), \
                "significant_at_005 should be bool"

    def test_pairwise_delta_sign(self):
        """delta_mrr must equal mrr(system_a) - mrr(system_b)."""
        with open('/app/output/audit_report.json', 'r') as f:
            report = json.load(f)
        system_mrrs = {s['name']: s['mrr_at_10'] for s in report['systems']}
        for pair in report['pairwise_significance']:
            a = pair['system_a']
            b = pair['system_b']
            expected_delta = system_mrrs[a] - system_mrrs[b]
            actual_delta = pair['delta_mrr']
            assert abs(actual_delta - expected_delta) < 1e-4, \
                "Delta MRR {}-{}: {} != expected {}".format(
                    a, b, actual_delta, expected_delta)
