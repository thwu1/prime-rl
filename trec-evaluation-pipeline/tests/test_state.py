"""Tests for the TREC evaluation campaign audit task.

Independently verifies that disqualification decisions are correct,
valid runs are properly identified, metrics match reference values,
and ranking follows MAP ordering.
"""

import json
import math
import os
import subprocess
from collections import defaultdict

import pytest

OUTPUT = '/app/output/audit.json'
DATA = '/app/campaign'
TREC_EVAL_BIN = '/app/trec_eval/trec_eval'

# Ground truth
EXPECTED_DISQUALIFIED = {'sys_bravo', 'sys_delta', 'sys_foxtrot'}
EXPECTED_VALID = sorted(['sys_alpha', 'sys_charlie', 'sys_echo'])
ALL_RUNS = ['sys_alpha', 'sys_bravo', 'sys_charlie',
            'sys_delta', 'sys_echo', 'sys_foxtrot']


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_qrels(path):
    qrels = defaultdict(dict)
    with open(path) as fh:
        for line in fh:
            parts = line.strip().split()
            if len(parts) >= 4:
                qrels[parts[0]][parts[2]] = int(parts[3])
    return dict(qrels)


def _load_run(path):
    run = defaultdict(list)
    with open(path) as fh:
        for line in fh:
            parts = line.strip().split()
            if len(parts) >= 6:
                try:
                    score = float(parts[4])
                    if math.isfinite(score):
                        run[parts[0]].append((parts[2], score))
                except ValueError:
                    pass
    for qid in run:
        run[qid].sort(key=lambda x: (-x[1], x[0]))
    return dict(run)


def _compute_map(run, qrels):
    aps = []
    for qid in sorted(qrels):
        total_rel = sum(1 for g in qrels[qid].values() if g > 0)
        if total_rel == 0:
            aps.append(0.0)
            continue
        hits = 0
        sum_prec = 0.0
        for i, (doc_id, _) in enumerate(run.get(qid, []), 1):
            if qrels[qid].get(doc_id, 0) > 0:
                hits += 1
                sum_prec += hits / i
        aps.append(sum_prec / total_rel)
    return sum(aps) / len(aps) if aps else 0.0


def _compute_p5(run, qrels):
    vals = []
    for qid in sorted(qrels):
        docs = run.get(qid, [])[:5]
        rel = sum(1 for d, _ in docs if qrels[qid].get(d, 0) > 0)
        vals.append(rel / 5.0)
    return sum(vals) / len(vals) if vals else 0.0


def _compute_ndcg10(run, qrels, use_exp_gain=True):
    vals = []
    for qid in sorted(qrels):
        docs = run.get(qid, [])[:10]
        dcg = 0.0
        for i, (doc_id, _) in enumerate(docs, 1):
            g = qrels[qid].get(doc_id, 0)
            gain = (2 ** g - 1) if use_exp_gain else g
            dcg += gain / math.log2(i + 1)
        all_gains = [(2 ** g - 1) if use_exp_gain else g
                     for g in qrels[qid].values()]
        all_gains.sort(reverse=True)
        idcg = sum(gain / math.log2(i + 1)
                   for i, gain in enumerate(all_gains[:10], 1))
        vals.append(dcg / idcg if idcg > 0 else 0.0)
    return sum(vals) / len(vals) if vals else 0.0


def _compute_judged_rate(run, qrels):
    total = 0
    judged = 0
    for qid, docs in run.items():
        for doc_id, _ in docs:
            total += 1
            if qid in qrels and doc_id in qrels[qid]:
                judged += 1
    return judged / total if total else 0.0


def _compute_top50_overlap(run_a, run_b, qrels):
    overlaps = []
    for qid in sorted(qrels):
        docs_a = set(d for d, _ in run_a.get(qid, [])[:50])
        docs_b = set(d for d, _ in run_b.get(qid, [])[:50])
        if docs_a and docs_b:
            overlaps.append(len(docs_a & docs_b) / 50.0)
    return sum(overlaps) / len(overlaps) if overlaps else 0.0


def _count_format_issues(path, valid_qids):
    """Count data quality problems in a run file."""
    issues = 0
    seen = defaultdict(set)
    with open(path) as fh:
        for line in fh:
            parts = line.strip().split()
            if len(parts) < 6:
                issues += 1
                continue
            qid, doc_id, score_str = parts[0], parts[2], parts[4]
            if qid not in valid_qids:
                issues += 1
                continue
            try:
                s = float(score_str)
                if not math.isfinite(s):
                    issues += 1
                    continue
            except (ValueError, OverflowError):
                issues += 1
                continue
            if doc_id in seen[qid]:
                issues += 1
                continue
            seen[qid].add(doc_id)
    return issues


def _try_trec_eval(run_path, qrels_path, metric):
    """Try running trec_eval binary to get a reference metric value."""
    if not os.path.isfile(TREC_EVAL_BIN):
        return None
    try:
        result = subprocess.run(
            [TREC_EVAL_BIN, '-m', metric, qrels_path, run_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.strip().split('\n'):
            parts = line.split()
            if len(parts) == 3 and parts[1] == 'all':
                return float(parts[2])
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def audit():
    assert os.path.isfile(OUTPUT), f'{OUTPUT} not found'
    with open(OUTPUT) as fh:
        return json.load(fh)


@pytest.fixture(scope='module')
def qrels():
    return _load_qrels(f'{DATA}/qrels')


@pytest.fixture(scope='module')
def all_runs():
    runs = {}
    for name in ALL_RUNS:
        path = f'{DATA}/{name}.txt'
        if os.path.isfile(path):
            runs[name] = _load_run(path)
    return runs


# ---------------------------------------------------------------------------
# 1. Output existence and structure
# ---------------------------------------------------------------------------

class TestStructure:

    def test_output_exists(self):
        assert os.path.isfile(OUTPUT)

    def test_has_required_fields(self, audit):
        for field in ['disqualified', 'valid_runs', 'metrics', 'ranking']:
            assert field in audit, f'Missing field: {field}'

    def test_disqualified_is_dict(self, audit):
        assert isinstance(audit['disqualified'], dict)

    def test_valid_runs_is_list(self, audit):
        assert isinstance(audit['valid_runs'], list)

    def test_metrics_is_dict(self, audit):
        assert isinstance(audit['metrics'], dict)

    def test_ranking_is_list(self, audit):
        assert isinstance(audit['ranking'], list)


# ---------------------------------------------------------------------------
# 2. Disqualification decisions
# ---------------------------------------------------------------------------

class TestDisqualifications:

    def test_bravo_disqualified(self, audit):
        assert 'sys_bravo' in audit['disqualified'], \
            'sys_bravo should be disqualified'

    def test_delta_disqualified(self, audit):
        assert 'sys_delta' in audit['disqualified'], \
            'sys_delta should be disqualified'

    def test_foxtrot_disqualified(self, audit):
        assert 'sys_foxtrot' in audit['disqualified'], \
            'sys_foxtrot should be disqualified'

    def test_exactly_three_disqualified(self, audit):
        assert len(audit['disqualified']) == 3, \
            f'Expected 3 disqualified, got {len(audit["disqualified"])}'

    def test_clean_runs_not_disqualified(self, audit):
        for run_id in EXPECTED_VALID:
            assert run_id not in audit['disqualified'], \
                f'Clean run {run_id} incorrectly disqualified'

    def test_disqualified_have_reasons(self, audit):
        for run_id, reason in audit['disqualified'].items():
            assert isinstance(reason, str), \
                f'Reason for {run_id} should be a string'
            assert len(reason) > 0, \
                f'Reason for {run_id} should not be empty'


# ---------------------------------------------------------------------------
# 3. Independent verification of data properties
#    (confirms the disqualifications are actually justified)
# ---------------------------------------------------------------------------

class TestDataProperties:

    def test_bravo_has_format_issues(self, qrels):
        """sys_bravo actually contains significant data quality problems."""
        path = f'{DATA}/sys_bravo.txt'
        valid_qids = set(qrels.keys())
        issues = _count_format_issues(path, valid_qids)
        assert issues > 50, \
            f'sys_bravo should have >50 format issues, found {issues}'

    def test_delta_has_anomalous_judged_rate(self, qrels, all_runs):
        """sys_delta actually has a judged-document rate near 1.0."""
        if 'sys_delta' not in all_runs:
            pytest.skip('sys_delta not loaded')
        delta_rate = _compute_judged_rate(all_runs['sys_delta'], qrels)
        assert delta_rate > 0.95, \
            f'sys_delta judged rate {delta_rate:.4f} should be >0.95'

    def test_delta_rate_exceeds_valid_runs(self, qrels, all_runs):
        """sys_delta judged rate exceeds every valid run's rate."""
        if 'sys_delta' not in all_runs:
            pytest.skip('sys_delta not loaded')
        delta_rate = _compute_judged_rate(all_runs['sys_delta'], qrels)
        for name in EXPECTED_VALID:
            if name in all_runs:
                other_rate = _compute_judged_rate(all_runs[name], qrels)
                assert delta_rate > other_rate, \
                    f'sys_delta rate {delta_rate:.4f} <= {name} rate {other_rate:.4f}'

    def test_foxtrot_charlie_overlap_very_high(self, qrels, all_runs):
        """sys_foxtrot and sys_charlie have extremely high document overlap."""
        if 'sys_foxtrot' not in all_runs or 'sys_charlie' not in all_runs:
            pytest.skip('runs not loaded')
        overlap = _compute_top50_overlap(
            all_runs['sys_foxtrot'], all_runs['sys_charlie'], qrels)
        assert overlap > 0.80, \
            f'foxtrot-charlie overlap {overlap:.4f} should be >0.80'

    def test_foxtrot_charlie_overlap_exceeds_other_pairs(self, qrels, all_runs):
        """foxtrot-charlie overlap far exceeds any legitimate pair."""
        if 'sys_foxtrot' not in all_runs or 'sys_charlie' not in all_runs:
            pytest.skip('runs not loaded')
        fc_overlap = _compute_top50_overlap(
            all_runs['sys_foxtrot'], all_runs['sys_charlie'], qrels)
        for name in EXPECTED_VALID:
            if name != 'sys_charlie' and name in all_runs:
                pair_overlap = _compute_top50_overlap(
                    all_runs[name], all_runs['sys_charlie'], qrels)
                assert fc_overlap > pair_overlap + 0.20, \
                    f'fc overlap {fc_overlap:.4f} not much higher than ' \
                    f'{name}-charlie overlap {pair_overlap:.4f}'

    def test_valid_runs_have_no_format_issues(self, qrels):
        """Confirm valid runs are actually clean."""
        valid_qids = set(qrels.keys())
        for name in EXPECTED_VALID:
            path = f'{DATA}/{name}.txt'
            issues = _count_format_issues(path, valid_qids)
            assert issues == 0, \
                f'{name} should have 0 format issues, found {issues}'


# ---------------------------------------------------------------------------
# 4. Valid runs
# ---------------------------------------------------------------------------

class TestValidRuns:

    def test_valid_runs_correct(self, audit):
        assert sorted(audit['valid_runs']) == EXPECTED_VALID, \
            f"Expected {EXPECTED_VALID}, got {sorted(audit['valid_runs'])}"

    def test_no_overlap_with_disqualified(self, audit):
        valid = set(audit['valid_runs'])
        disq = set(audit['disqualified'].keys())
        overlap = valid & disq
        assert not overlap, \
            f'Runs appear in both valid and disqualified: {overlap}'


# ---------------------------------------------------------------------------
# 5. Metrics
# ---------------------------------------------------------------------------

class TestMetrics:

    def test_all_valid_runs_have_metrics(self, audit):
        for run_id in EXPECTED_VALID:
            assert run_id in audit['metrics'], \
                f'Missing metrics for {run_id}'
            for m in ['map', 'ndcg_cut_10', 'P_5']:
                assert m in audit['metrics'][run_id], \
                    f'Missing {m} for {run_id}'

    def test_metric_ranges(self, audit):
        for run_id in audit['valid_runs']:
            if run_id not in audit['metrics']:
                continue
            for m in ['map', 'ndcg_cut_10', 'P_5']:
                val = audit['metrics'][run_id][m]
                assert 0 <= val <= 1, \
                    f'{m} for {run_id} = {val} out of [0,1]'

    def test_map_values(self, audit, qrels, all_runs):
        for run_id in EXPECTED_VALID:
            if run_id not in all_runs:
                continue
            expected = _compute_map(all_runs[run_id], qrels)
            actual = audit['metrics'][run_id]['map']
            ref = _try_trec_eval(
                f'{DATA}/{run_id}.txt', f'{DATA}/qrels', 'map')
            if ref is not None:
                assert abs(actual - ref) < 0.005, \
                    f'MAP {run_id}: got {actual}, trec_eval says {ref}'
            else:
                assert abs(actual - expected) < 0.005, \
                    f'MAP {run_id}: got {actual}, expected {expected}'

    def test_p5_values(self, audit, qrels, all_runs):
        for run_id in EXPECTED_VALID:
            if run_id not in all_runs:
                continue
            expected = _compute_p5(all_runs[run_id], qrels)
            actual = audit['metrics'][run_id]['P_5']
            ref = _try_trec_eval(
                f'{DATA}/{run_id}.txt', f'{DATA}/qrels', 'P.5')
            if ref is not None:
                assert abs(actual - ref) < 0.005, \
                    f'P@5 {run_id}: got {actual}, trec_eval says {ref}'
            else:
                assert abs(actual - expected) < 0.005, \
                    f'P@5 {run_id}: got {actual}, expected {expected}'

    def test_ndcg10_values(self, audit, qrels, all_runs):
        for run_id in EXPECTED_VALID:
            if run_id not in all_runs:
                continue
            exp_gain = _compute_ndcg10(
                all_runs[run_id], qrels, use_exp_gain=True)
            raw_gain = _compute_ndcg10(
                all_runs[run_id], qrels, use_exp_gain=False)
            actual = audit['metrics'][run_id]['ndcg_cut_10']
            ref = _try_trec_eval(
                f'{DATA}/{run_id}.txt', f'{DATA}/qrels', 'ndcg_cut.10')
            if ref is not None:
                assert abs(actual - ref) < 0.005, \
                    f'nDCG@10 {run_id}: got {actual}, trec_eval={ref}'
            else:
                err = min(abs(actual - exp_gain), abs(actual - raw_gain))
                assert err < 0.01, \
                    f'nDCG@10 {run_id}: got {actual}, ' \
                    f'exp={exp_gain:.4f}, raw={raw_gain:.4f}'

    def test_only_valid_runs_have_metrics(self, audit):
        extra = set(audit['metrics'].keys()) - set(EXPECTED_VALID)
        assert not extra, \
            f'Metrics computed for non-valid runs: {extra}'


# ---------------------------------------------------------------------------
# 6. Ranking
# ---------------------------------------------------------------------------

class TestRanking:

    def test_ranking_matches_valid(self, audit):
        assert set(audit['ranking']) == set(EXPECTED_VALID)

    def test_ranking_by_map(self, audit):
        for i in range(len(audit['ranking']) - 1):
            r1 = audit['ranking'][i]
            r2 = audit['ranking'][i + 1]
            m1 = audit['metrics'][r1]['map']
            m2 = audit['metrics'][r2]['map']
            assert m1 >= m2 - 0.001, \
                f'{r1} (MAP={m1}) ranked above {r2} (MAP={m2}) incorrectly'

    def test_charlie_best(self, audit):
        assert audit['ranking'][0] == 'sys_charlie', \
            f'Expected sys_charlie as best, got {audit["ranking"][0]}'

    def test_echo_worst(self, audit):
        assert audit['ranking'][-1] == 'sys_echo', \
            f'Expected sys_echo as worst, got {audit["ranking"][-1]}'
