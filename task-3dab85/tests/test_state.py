"""Tests for IR evaluation pipeline — outcome verification.

Independently computes metrics from agent's cleaned runs and
compares against agent's reported evaluation outputs.
"""

import json
import math
import os
from collections import defaultdict

import pytest
from scipy import stats as scipy_stats

TOL = 1e-4
OUT = "/app/output"
SYSTEMS = ["alpha", "beta", "gamma", "delta", "epsilon"]
METRICS = [
    "ndcg_cut_10", "ndcg_cut_100", "ndcg_cut_1000",
    "map", "recip_rank", "recall_100", "recall_1000",
]


# =========== helpers ===========

def load_qrels(path="/app/qrels.txt"):
    qrels = defaultdict(dict)
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            qid, docid, rel = parts[0], parts[2], int(parts[3])
            qrels[qid][docid] = rel
    return dict(qrels)


def load_run(path):
    run = defaultdict(list)
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 6:
                continue
            qid, docid = parts[0], parts[2]
            rank, score = int(parts[3]), float(parts[4])
            run[qid].append((docid, rank, score))
    for qid in run:
        run[qid].sort(key=lambda x: x[1])
    return dict(run)


def _ndcg(qrels_q, entries, k):
    dcg = 0.0
    for i, (docid, _, _) in enumerate(entries[:k]):
        rel = qrels_q.get(docid, 0)
        dcg += ((2 ** rel) - 1) / math.log2(i + 2)
    ideal = sorted(qrels_q.values(), reverse=True)[:k]
    idcg = sum(((2 ** r) - 1) / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def _ap(qrels_q, entries):
    total_rel = sum(1 for v in qrels_q.values() if v > 0)
    if total_rel == 0:
        return 0.0
    found = 0
    ap_sum = 0.0
    for i, (docid, _, _) in enumerate(entries):
        if qrels_q.get(docid, 0) > 0:
            found += 1
            ap_sum += found / (i + 1)
    return ap_sum / total_rel


def _rr(qrels_q, entries):
    for i, (docid, _, _) in enumerate(entries):
        if qrels_q.get(docid, 0) > 0:
            return 1.0 / (i + 1)
    return 0.0


def _recall(qrels_q, entries, k):
    total_rel = sum(1 for v in qrels_q.values() if v > 0)
    if total_rel == 0:
        return 0.0
    found = sum(1 for docid, _, _ in entries[:k] if qrels_q.get(docid, 0) > 0)
    return found / total_rel


def eval_run(qrels, run):
    results = {}
    for metric in METRICS:
        per_q = {}
        for qid in qrels:
            ents = run.get(qid, [])
            qq = qrels[qid]
            if metric == "ndcg_cut_10":
                per_q[qid] = _ndcg(qq, ents, 10)
            elif metric == "ndcg_cut_100":
                per_q[qid] = _ndcg(qq, ents, 100)
            elif metric == "ndcg_cut_1000":
                per_q[qid] = _ndcg(qq, ents, 1000)
            elif metric == "map":
                per_q[qid] = _ap(qq, ents)
            elif metric == "recip_rank":
                per_q[qid] = _rr(qq, ents)
            elif metric == "recall_100":
                per_q[qid] = _recall(qq, ents, 100)
            elif metric == "recall_1000":
                per_q[qid] = _recall(qq, ents, 1000)
        results[metric] = per_q
    return results


def _mean(vals):
    v = list(vals)
    return sum(v) / len(v) if v else 0.0


# =========== fixtures ===========

@pytest.fixture(scope="module")
def qrels():
    return load_qrels()


@pytest.fixture(scope="module")
def cleaned_runs():
    runs = {}
    for sys in SYSTEMS:
        path = f"{OUT}/cleaned_runs/run_{sys}.txt"
        if os.path.isfile(path):
            runs[sys] = load_run(path)
    return runs


@pytest.fixture(scope="module")
def agent_evals():
    evals = {}
    for sys in SYSTEMS:
        path = f"{OUT}/eval_{sys}.json"
        if os.path.isfile(path):
            with open(path) as f:
                evals[sys] = json.load(f)
    return evals


@pytest.fixture(scope="module")
def combined_run():
    path = f"{OUT}/combined.txt"
    if os.path.isfile(path):
        return load_run(path)
    return None


@pytest.fixture(scope="module")
def combined_eval():
    path = f"{OUT}/eval_combined.json"
    if os.path.isfile(path):
        with open(path) as f:
            return json.load(f)
    return None


# =========== TestOutputFiles ===========

class TestOutputFiles:
    @pytest.mark.parametrize("fname", [
        "diagnostics.json",
        "eval_alpha.json", "eval_beta.json", "eval_gamma.json",
        "eval_delta.json", "eval_epsilon.json",
        "combined.txt", "eval_combined.json", "significance.json",
    ])
    def test_output_exists(self, fname):
        assert os.path.isfile(f"{OUT}/{fname}"), f"Missing: {fname}"

    def test_cleaned_runs_dir_exists(self):
        assert os.path.isdir(f"{OUT}/cleaned_runs")

    @pytest.mark.parametrize("sys", SYSTEMS)
    def test_cleaned_run_file_exists(self, sys):
        assert os.path.isfile(f"{OUT}/cleaned_runs/run_{sys}.txt"), \
            f"Missing cleaned_runs/run_{sys}.txt"


# =========== TestDiagnostics ===========

class TestDiagnostics:
    def _diag(self):
        with open(f"{OUT}/diagnostics.json") as f:
            return json.load(f)

    def _text(self, diag, sys):
        # Try common key conventions the agent might use
        for key in [sys, f"run_{sys}", f"run_{sys}.txt"]:
            if key in diag:
                return json.dumps(diag[key]).lower()
        return ""

    def test_alpha_duplicates_detected(self):
        txt = self._text(self._diag(), "alpha")
        assert any(kw in txt for kw in [
            "duplicate", "dup ", "dups", "repeated", "multiple occurrences",
            "appears more than once", "same doc",
        ]), "Should identify duplicate documents in alpha"

    def test_beta_zero_indexed_detected(self):
        txt = self._text(self._diag(), "beta")
        assert any(kw in txt for kw in [
            "0-index", "zero-index", "zero index", "0 index",
            "starts at 0", "start from 0", "rank 0", "minimum rank",
            "begins at 0", "0-based",
        ]), "Should identify 0-indexed ranks in beta"

    def test_gamma_inversion_detected(self):
        txt = self._text(self._diag(), "gamma")
        assert any(kw in txt for kw in [
            "invert", "inversion", "ascending", "inconsisten",
            "mismatch", "revers", "disagree", "conflict",
            "wrong order", "score order", "score-rank", "not descending",
            "increasing",
        ]), "Should identify score-rank inversion in gamma"

    def test_delta_qid_padding_detected(self):
        txt = self._text(self._diag(), "delta")
        assert any(kw in txt for kw in [
            "pad", "leading zero", "zero-pad", "query id",
            "qid", "inconsistent", "format", "mismatch",
            "normalize", "leading 0",
        ]), "Should identify zero-padded query IDs in delta"


# =========== TestCleanedRunFormat ===========

class TestCleanedRunFormat:
    @pytest.mark.parametrize("sys", SYSTEMS)
    def test_six_columns(self, sys):
        path = f"{OUT}/cleaned_runs/run_{sys}.txt"
        with open(path) as f:
            for i, line in enumerate(f):
                parts = line.strip().split()
                assert len(parts) == 6, \
                    f"run_{sys}.txt line {i+1}: {len(parts)} cols, need 6"

    @pytest.mark.parametrize("sys", SYSTEMS)
    def test_no_duplicate_docs(self, sys):
        run = load_run(f"{OUT}/cleaned_runs/run_{sys}.txt")
        for qid, entries in run.items():
            docs = [d for d, _, _ in entries]
            assert len(docs) == len(set(docs)), \
                f"run_{sys} query {qid}: duplicate documents found"

    @pytest.mark.parametrize("sys", SYSTEMS)
    def test_ranks_start_at_one(self, sys):
        run = load_run(f"{OUT}/cleaned_runs/run_{sys}.txt")
        for qid, entries in run.items():
            ranks = [r for _, r, _ in entries]
            assert min(ranks) >= 1, \
                f"run_{sys} query {qid}: min rank={min(ranks)}, expected >= 1"

    @pytest.mark.parametrize("sys", SYSTEMS)
    def test_scores_non_increasing(self, sys):
        run = load_run(f"{OUT}/cleaned_runs/run_{sys}.txt")
        for qid, entries in run.items():
            scores = [s for _, _, s in entries]
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1] - 1e-10, \
                    f"run_{sys} query {qid}: scores not descending at rank {i+1}"

    @pytest.mark.parametrize("sys", SYSTEMS)
    def test_query_coverage(self, sys, qrels):
        run = load_run(f"{OUT}/cleaned_runs/run_{sys}.txt")
        assert len(run) == len(qrels), \
            f"run_{sys}: {len(run)} queries, expected {len(qrels)}"
        for qid in qrels:
            assert qid in run, f"run_{sys}: missing query {qid}"


# =========== TestMetricsAccuracy ===========

class TestMetricsAccuracy:
    @pytest.mark.parametrize("sys", SYSTEMS)
    def test_mean_metrics_match(self, sys, qrels, cleaned_runs, agent_evals):
        if sys not in cleaned_runs or sys not in agent_evals:
            pytest.skip(f"Missing data for {sys}")
        ref = eval_run(qrels, cleaned_runs[sys])
        agent = agent_evals[sys]
        for metric in METRICS:
            ref_mean = _mean(ref[metric].values())
            agent_mean = agent["mean"][metric]
            assert abs(ref_mean - agent_mean) < TOL, (
                f"{sys} mean {metric}: ref={ref_mean:.6f}, agent={agent_mean:.6f}"
            )

    @pytest.mark.parametrize("sys", SYSTEMS)
    def test_per_query_metrics_match(self, sys, qrels, cleaned_runs, agent_evals):
        if sys not in cleaned_runs or sys not in agent_evals:
            pytest.skip(f"Missing data for {sys}")
        ref = eval_run(qrels, cleaned_runs[sys])
        agent = agent_evals[sys]
        for metric in METRICS:
            for qid in qrels:
                rv = ref[metric][qid]
                av = agent["per_query"][qid][metric]
                assert abs(rv - av) < TOL, (
                    f"{sys} q{qid} {metric}: ref={rv:.6f}, agent={av:.6f}"
                )

    def test_all_metrics_present(self, agent_evals):
        for sys in SYSTEMS:
            if sys not in agent_evals:
                pytest.fail(f"Missing eval for {sys}")
            for metric in METRICS:
                assert metric in agent_evals[sys]["mean"], \
                    f"{sys} missing mean metric {metric}"


# =========== TestCombinedRun ===========

class TestCombinedRun:
    def test_combined_valid_format(self, qrels, combined_run):
        assert combined_run is not None, "combined.txt not found or not parseable"
        for qid, entries in combined_run.items():
            assert len(entries) <= 1000, \
                f"Query {qid}: {len(entries)} results, max 1000"
            scores = [s for _, _, s in entries]
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1] - 1e-10, \
                    f"Query {qid}: scores not descending"

    def test_combined_run_id(self):
        with open(f"{OUT}/combined.txt") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 6:
                    assert parts[5] == "COMBINED", \
                        f"Run ID should be 'COMBINED', got '{parts[5]}'"
                    break

    def test_combined_query_coverage(self, qrels, combined_run):
        assert combined_run is not None
        for qid in qrels:
            assert qid in combined_run, f"Combined run missing query {qid}"

    def test_combined_beats_all_individuals(self, qrels, combined_run, cleaned_runs):
        assert combined_run is not None
        ref_c = eval_run(qrels, combined_run)
        c_mean = _mean(ref_c["ndcg_cut_10"].values())

        for sys in SYSTEMS:
            if sys not in cleaned_runs:
                pytest.fail(f"Missing cleaned run for {sys}")
            ref_s = eval_run(qrels, cleaned_runs[sys])
            s_mean = _mean(ref_s["ndcg_cut_10"].values())
            assert c_mean > s_mean - TOL, (
                f"Combined nDCG@10 ({c_mean:.4f}) must beat "
                f"{sys} ({s_mean:.4f})"
            )

    def test_combined_eval_consistency(self, qrels, combined_run, combined_eval):
        assert combined_run is not None and combined_eval is not None
        ref = eval_run(qrels, combined_run)
        for metric in METRICS:
            ref_mean = _mean(ref[metric].values())
            agent_mean = combined_eval["mean"][metric]
            assert abs(ref_mean - agent_mean) < TOL, (
                f"Combined {metric}: ref={ref_mean:.6f}, agent={agent_mean:.6f}"
            )


# =========== TestSignificance ===========

class TestSignificance:
    def _sig(self):
        with open(f"{OUT}/significance.json") as f:
            return json.load(f)

    @pytest.mark.parametrize("sys", SYSTEMS)
    def test_entry_structure(self, sys):
        sig = self._sig()
        assert sys in sig, f"Missing significance entry for {sys}"
        entry = sig[sys]
        for field in ["test_name", "statistic", "p_value", "significant_at_005"]:
            assert field in entry, f"Missing '{field}' for {sys}"

    @pytest.mark.parametrize("sys", SYSTEMS)
    def test_p_value_valid(self, sys):
        entry = self._sig()[sys]
        assert 0 <= entry["p_value"] <= 1, \
            f"{sys}: p_value {entry['p_value']} out of [0,1]"

    @pytest.mark.parametrize("sys", SYSTEMS)
    def test_significance_flag_consistent(self, sys):
        entry = self._sig()[sys]
        expected = entry["p_value"] < 0.05
        assert entry["significant_at_005"] == expected, (
            f"{sys}: p={entry['p_value']:.4f}, "
            f"flag should be {expected}"
        )

    def test_significance_agreement_with_reference(self, qrels, combined_run, cleaned_runs):
        """Verify agent's significance decisions match independent computation."""
        if combined_run is None:
            pytest.skip("No combined run")
        sig = self._sig()
        ref_c = eval_run(qrels, combined_run)
        cvals = ref_c["ndcg_cut_10"]
        qids = sorted(qrels.keys(), key=int)

        for sys in SYSTEMS:
            if sys not in cleaned_runs or sys not in sig:
                continue
            ref_s = eval_run(qrels, cleaned_runs[sys])
            svals = ref_s["ndcg_cut_10"]

            x = [cvals.get(q, 0.0) for q in qids]
            y = [svals.get(q, 0.0) for q in qids]
            diffs = [a - b for a, b in zip(x, y)]

            # Compute reference with paired t-test and Wilcoxon
            try:
                _, t_pval = scipy_stats.ttest_rel(x, y)
            except Exception:
                t_pval = 1.0
            try:
                w_res = scipy_stats.wilcoxon(diffs, alternative="two-sided")
                w_pval = w_res.pvalue
            except Exception:
                w_pval = 1.0

            agent_p = sig[sys]["p_value"]
            # Agent's significance decision should agree with at least one reference test
            t_agree = (agent_p < 0.05) == (t_pval < 0.05)
            w_agree = (agent_p < 0.05) == (w_pval < 0.05)
            assert t_agree or w_agree, (
                f"{sys}: agent p={agent_p:.4f} disagrees with "
                f"t-test (p={t_pval:.4f}) and Wilcoxon (p={w_pval:.4f}) "
                f"on significance decision"
            )
