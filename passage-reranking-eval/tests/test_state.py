#!/usr/bin/env python3
"""
Tests for the IR Pipeline Forensics task.
Verifies bug diagnosis, corrected BM25 output in dual formats, and metric accuracy.
"""


import json
import math
import os
import re
import subprocess
from collections import defaultdict

import pytest

DATA_DIR = "/app/data"
OUT_DIR = "/app/output"
QRELS_PATH = os.path.join(DATA_DIR, "qrels.tsv")
BM25_MSMARCO_PATH = os.path.join(OUT_DIR, "bm25_run.tsv")
BM25_TREC_PATH = os.path.join(OUT_DIR, "bm25_run.trec")
METRICS_PATH = os.path.join(OUT_DIR, "metrics.json")
BUG_REPORT_PATH = os.path.join(OUT_DIR, "bug_report.json")

REQUIRED_RUNS = ["random_run", "tfidf_run", "oracle_run", "bm25_run"]
REQUIRED_METRICS = ["MRR@10", "NDCG@10", "MAP", "Recall@10", "Recall@100"]
MRR_THRESHOLD = 0.30

PIPELINE_FILES = {"tokenizer.py", "index.py", "bm25.py", "run_pipeline.py"}


# ── Helper: load data ───────────────────────────────────────────────────────

def _load_qrels():
    qrels = {}
    with open(QRELS_PATH) as f:
        for line in f:
            parts = line.strip().split("\t")
            qid, pid = int(parts[0]), int(parts[2])
            qrels.setdefault(qid, set()).add(pid)
    return qrels


def _load_run(path):
    raw = defaultdict(dict)
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t")
            qid, pid, rank = int(parts[0]), int(parts[1]), int(parts[2])
            raw[qid][rank] = pid
    result = {}
    for qid, rm in raw.items():
        mx = max(rm.keys())
        result[qid] = [rm.get(r, 0) for r in range(1, mx + 1)]
    return result


# ── Helper: reference metric implementations ────────────────────────────────

def _ref_mrr10(qrels, run):
    s = 0.0
    for qid, rels in qrels.items():
        if qid not in run:
            continue
        for i in range(min(10, len(run[qid]))):
            if run[qid][i] in rels:
                s += 1.0 / (i + 1)
                break
    return s / len(qrels)


def _ref_ndcg10(qrels, run):
    s = 0.0
    for qid, rels in qrels.items():
        if qid not in run:
            continue
        dcg = 0.0
        for i in range(min(10, len(run[qid]))):
            if run[qid][i] in rels:
                dcg += 1.0 / math.log2(i + 2)
        n_rel = len(rels)
        idcg = sum(1.0 / math.log2(j + 2) for j in range(min(n_rel, 10)))
        if idcg > 0:
            s += dcg / idcg
    return s / len(qrels)


def _ref_map(qrels, run):
    s = 0.0
    for qid, rels in qrels.items():
        if qid not in run:
            continue
        found = 0
        ap = 0.0
        for i in range(len(run[qid])):
            if run[qid][i] in rels:
                found += 1
                ap += found / (i + 1)
        if len(rels) > 0:
            s += ap / len(rels)
    return s / len(qrels)


def _ref_recall(qrels, run, k):
    s = 0.0
    for qid, rels in qrels.items():
        if qid not in run:
            continue
        retrieved = set(run[qid][: min(k, len(run[qid]))])
        s += len(retrieved & rels) / len(rels)
    return s / len(qrels)


# ── 1. Output files exist ───────────────────────────────────────────────────

def test_bug_report_exists():
    assert os.path.isfile(BUG_REPORT_PATH), "bug_report.json not found"


def test_bm25_msmarco_exists():
    assert os.path.isfile(BM25_MSMARCO_PATH), "bm25_run.tsv not found"


def test_bm25_trec_exists():
    assert os.path.isfile(BM25_TREC_PATH), "bm25_run.trec not found"


def test_metrics_json_exists():
    assert os.path.isfile(METRICS_PATH), "metrics.json not found"


# ── 2. Bug report structure and coverage ─────────────────────────────────────

def test_bug_report_structure():
    with open(BUG_REPORT_PATH) as f:
        report = json.load(f)
    assert "bugs" in report, "bug_report.json missing 'bugs' key"
    bugs = report["bugs"]
    assert isinstance(bugs, list), "'bugs' must be a list"
    assert len(bugs) >= 3, f"Expected at least 3 bugs, found {len(bugs)}"
    for i, bug in enumerate(bugs):
        assert "file" in bug, f"Bug {i} missing 'file' key"
        assert "description" in bug, f"Bug {i} missing 'description' key"
        assert "fix" in bug, f"Bug {i} missing 'fix' key"


def test_bug_report_coverage():
    """Bug report should identify bugs in at least 3 of the 4 pipeline modules."""
    with open(BUG_REPORT_PATH) as f:
        report = json.load(f)
    reported_files = set()
    for bug in report["bugs"]:
        fname = bug["file"]
        # Normalize: strip path, keep just filename
        fname = os.path.basename(fname)
        reported_files.add(fname)
    covered = reported_files & PIPELINE_FILES
    assert len(covered) >= 3, (
        f"Bug report covers {covered} but should identify bugs in at least 3 of {PIPELINE_FILES}"
    )


# ── 3. BM25 MS MARCO format ─────────────────────────────────────────────────

def test_bm25_msmarco_format():
    qids_seen = set()
    with open(BM25_MSMARCO_PATH) as f:
        for lineno, line in enumerate(f, 1):
            parts = line.strip().split("\t")
            assert len(parts) == 3, (
                f"Line {lineno}: expected 3 tab-separated fields, got {len(parts)}"
            )
            qid, pid, rank = int(parts[0]), int(parts[1]), int(parts[2])
            assert rank >= 1, f"Line {lineno}: rank must be >= 1 (got {rank})"
            qids_seen.add(qid)
    qrels = _load_qrels()
    covered = qids_seen & set(qrels.keys())
    assert len(covered) >= 180, (
        f"BM25 run covers {len(covered)} of {len(qrels)} qrel queries (need >= 180)"
    )


def test_bm25_no_duplicate_pids():
    """No passage should appear at two different ranks for the same query."""
    qid_pids = defaultdict(list)
    with open(BM25_MSMARCO_PATH) as f:
        for line in f:
            parts = line.strip().split("\t")
            qid, pid = int(parts[0]), int(parts[1])
            qid_pids[qid].append(pid)
    for qid, pids in qid_pids.items():
        assert len(pids) == len(set(pids)), f"Duplicate PIDs for QID {qid}"


# ── 4. BM25 TREC format ─────────────────────────────────────────────────────

def test_bm25_trec_format():
    """TREC format: qid Q0 pid rank score tag (space-separated)."""
    with open(BM25_TREC_PATH) as f:
        for lineno, line in enumerate(f, 1):
            fields = line.strip().split()
            assert len(fields) == 6, (
                f"TREC line {lineno}: expected 6 space-separated fields, got {len(fields)}"
            )
            qid_str, q0, pid_str, rank_str, score_str, tag = fields
            assert q0 == "Q0", f"TREC line {lineno}: field 2 should be 'Q0', got '{q0}'"
            int(qid_str)  # must be parseable as int
            int(pid_str)
            int(rank_str)
            float(score_str)
            assert rank_str != "0", f"TREC line {lineno}: rank should be 1-indexed"
            assert tag == "bm25", f"TREC line {lineno}: tag should be 'bm25', got '{tag}'"


def test_trec_scores_decreasing():
    """Within each query, TREC scores must be monotonically non-increasing."""
    query_scores = defaultdict(list)
    with open(BM25_TREC_PATH) as f:
        for line in f:
            fields = line.strip().split()
            qid = int(fields[0])
            rank = int(fields[3])
            score = float(fields[4])
            query_scores[qid].append((rank, score))
    for qid, entries in query_scores.items():
        entries.sort(key=lambda x: x[0])
        for i in range(1, len(entries)):
            assert entries[i][1] <= entries[i - 1][1] + 1e-9, (
                f"QID {qid}: score at rank {entries[i][0]} ({entries[i][1]}) > "
                f"score at rank {entries[i-1][0]} ({entries[i-1][1]})"
            )


# ── 5. Cross-format consistency ──────────────────────────────────────────────

def test_run_format_consistency():
    """Both TREC and MS MARCO files must encode the same ranking."""
    msmarco_ranking = defaultdict(list)
    with open(BM25_MSMARCO_PATH) as f:
        for line in f:
            parts = line.strip().split("\t")
            qid, pid, rank = int(parts[0]), int(parts[1]), int(parts[2])
            msmarco_ranking[qid].append((rank, pid))

    trec_ranking = defaultdict(list)
    with open(BM25_TREC_PATH) as f:
        for line in f:
            fields = line.strip().split()
            qid, pid, rank = int(fields[0]), int(fields[2]), int(fields[3])
            trec_ranking[qid].append((rank, pid))

    assert set(msmarco_ranking.keys()) == set(trec_ranking.keys()), (
        "TREC and MS MARCO files cover different query sets"
    )

    for qid in msmarco_ranking:
        ms_sorted = sorted(msmarco_ranking[qid])
        tr_sorted = sorted(trec_ranking[qid])
        ms_pids = [pid for _, pid in ms_sorted]
        tr_pids = [pid for _, pid in tr_sorted]
        assert ms_pids == tr_pids, (
            f"QID {qid}: rankings differ between TREC and MS MARCO formats"
        )


# ── 6. BM25 MRR@10 threshold ────────────────────────────────────────────────

def test_bm25_mrr_threshold_official():
    """BM25 run must achieve MRR@10 >= 0.30 (verified by official eval script)."""
    result = subprocess.run(
        ["python3", os.path.join(DATA_DIR, "ms_marco_eval.py"),
         QRELS_PATH, BM25_MSMARCO_PATH],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Eval script failed: {result.stderr}"
    m = re.search(r"MRR @10:\s*([0-9.]+)", result.stdout)
    assert m is not None, f"Could not parse MRR from eval output: {result.stdout}"
    mrr = float(m.group(1))
    assert mrr >= MRR_THRESHOLD, f"BM25 MRR@10 = {mrr:.4f} < {MRR_THRESHOLD}"


# ── 7. metrics.json structure ────────────────────────────────────────────────

def test_metrics_json_structure():
    with open(METRICS_PATH) as f:
        metrics = json.load(f)
    for run_name in REQUIRED_RUNS:
        assert run_name in metrics, f"Missing run '{run_name}' in metrics.json"
        for metric_name in REQUIRED_METRICS:
            assert metric_name in metrics[run_name], (
                f"Missing metric '{metric_name}' for run '{run_name}'"
            )
            val = metrics[run_name][metric_name]
            assert isinstance(val, (int, float)), (
                f"Metric value for {run_name}/{metric_name} is not numeric"
            )


# ── 8. MRR@10 agreement with official eval script ───────────────────────────

def test_mrr_agreement_baselines():
    """Agent MRR@10 values must match official eval script (tolerance 0.002)."""
    with open(METRICS_PATH) as f:
        agent = json.load(f)

    for run_name in ["random_run", "tfidf_run", "oracle_run"]:
        run_path = os.path.join(DATA_DIR, "runs", f"{run_name}.tsv")
        result = subprocess.run(
            ["python3", os.path.join(DATA_DIR, "ms_marco_eval.py"),
             QRELS_PATH, run_path],
            capture_output=True, text=True,
        )
        m = re.search(r"MRR @10:\s*([0-9.]+)", result.stdout)
        assert m is not None, f"Could not parse MRR for {run_name}"
        official = float(m.group(1))
        agent_val = agent[run_name]["MRR@10"]
        assert abs(official - agent_val) < 0.002, (
            f"MRR mismatch for {run_name}: official={official:.6f}, agent={agent_val:.6f}"
        )


# ── 9. Oracle metrics must all be 1.0 ───────────────────────────────────────

def test_oracle_metrics():
    with open(METRICS_PATH) as f:
        metrics = json.load(f)
    oracle = metrics["oracle_run"]
    for m_name in REQUIRED_METRICS:
        assert abs(oracle[m_name] - 1.0) < 0.001, (
            f"Oracle {m_name} = {oracle[m_name]}, expected 1.0"
        )


# ── 10. Recall@100 = 1.0 for all baseline runs ──────────────────────────────

def test_recall_100_baselines():
    with open(METRICS_PATH) as f:
        metrics = json.load(f)
    for run_name in ["random_run", "tfidf_run", "oracle_run"]:
        val = metrics[run_name]["Recall@100"]
        assert abs(val - 1.0) < 0.001, (
            f"Recall@100 for {run_name} = {val}, expected 1.0"
        )


# ── 11. NDCG@10 reference check ─────────────────────────────────────────────

def test_ndcg_reference_values():
    """NDCG@10 must match independent reference computation (tolerance 0.005)."""
    with open(METRICS_PATH) as f:
        agent = json.load(f)
    qrels = _load_qrels()

    for run_name in ["random_run", "tfidf_run", "oracle_run"]:
        run_path = os.path.join(DATA_DIR, "runs", f"{run_name}.tsv")
        run = _load_run(run_path)
        ref = _ref_ndcg10(qrels, run)
        agent_val = agent[run_name]["NDCG@10"]
        assert abs(ref - agent_val) < 0.005, (
            f"NDCG@10 mismatch for {run_name}: ref={ref:.6f}, agent={agent_val:.6f}"
        )


# ── 12. MAP reference check ─────────────────────────────────────────────────

def test_map_reference_values():
    """MAP must match independent reference computation (tolerance 0.005)."""
    with open(METRICS_PATH) as f:
        agent = json.load(f)
    qrels = _load_qrels()

    for run_name in ["random_run", "tfidf_run", "oracle_run"]:
        run_path = os.path.join(DATA_DIR, "runs", f"{run_name}.tsv")
        run = _load_run(run_path)
        ref = _ref_map(qrels, run)
        agent_val = agent[run_name]["MAP"]
        assert abs(ref - agent_val) < 0.005, (
            f"MAP mismatch for {run_name}: ref={ref:.6f}, agent={agent_val:.6f}"
        )


# ── 13. Recall@10 reference check ───────────────────────────────────────────

def test_recall10_reference_values():
    """Recall@10 must match independent reference computation (tolerance 0.005)."""
    with open(METRICS_PATH) as f:
        agent = json.load(f)
    qrels = _load_qrels()

    for run_name in ["random_run", "tfidf_run", "oracle_run"]:
        run_path = os.path.join(DATA_DIR, "runs", f"{run_name}.tsv")
        run = _load_run(run_path)
        ref = _ref_recall(qrels, run, 10)
        agent_val = agent[run_name]["Recall@10"]
        assert abs(ref - agent_val) < 0.005, (
            f"Recall@10 mismatch for {run_name}: ref={ref:.6f}, agent={agent_val:.6f}"
        )


# ── 14. BM25 beats random ───────────────────────────────────────────────────

def test_bm25_beats_random():
    with open(METRICS_PATH) as f:
        metrics = json.load(f)
    bm25_mrr = metrics["bm25_run"]["MRR@10"]
    random_mrr = metrics["random_run"]["MRR@10"]
    assert bm25_mrr > random_mrr + 0.05, (
        f"BM25 MRR@10 ({bm25_mrr:.4f}) should clearly beat random ({random_mrr:.4f})"
    )


# ── 15. No external IR libraries ────────────────────────────────────────────

def test_no_external_ir_libraries():
    """Agent must not use pyserini, rank_bm25, or similar IR libraries."""
    banned = ["pyserini", "rank_bm25", "matchzoo", "beir", "pytrec_eval"]
    for root, dirs, files in os.walk("/app"):
        if "/data" in root or "__pycache__" in root or "/.cache" in root:
            continue
        if "/pipeline" in root:
            continue  # skip the original buggy pipeline
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                content = open(fpath).read()
            except Exception:
                continue
            for lib in banned:
                assert f"import {lib}" not in content and f"from {lib}" not in content, (
                    f"External IR library '{lib}' detected in {fpath}"
                )


# ── 16. Metric value ranges ─────────────────────────────────────────────────

def test_metric_ranges():
    """All metrics must be in [0, 1]."""
    with open(METRICS_PATH) as f:
        metrics = json.load(f)
    for run_name, run_metrics in metrics.items():
        for m_name, val in run_metrics.items():
            assert 0.0 <= val <= 1.0 + 1e-9, (
                f"{run_name}/{m_name} = {val} is out of range [0, 1]"
            )


# ── 17. Random NDCG@10 sanity ───────────────────────────────────────────────

def test_random_ndcg_is_low():
    with open(METRICS_PATH) as f:
        metrics = json.load(f)
    val = metrics["random_run"]["NDCG@10"]
    assert val < 0.15, f"Random NDCG@10 = {val}, suspiciously high (expected < 0.15)"


# ── 18. BM25 NDCG/MRR consistency ───────────────────────────────────────────

def test_bm25_ndcg_mrr_consistency():
    """With 1 relevant doc per query, NDCG@10 >= MRR@10 (within tolerance)."""
    with open(METRICS_PATH) as f:
        metrics = json.load(f)
    bm25 = metrics["bm25_run"]
    assert bm25["NDCG@10"] >= bm25["MRR@10"] - 0.01, (
        f"NDCG@10 ({bm25['NDCG@10']:.4f}) unexpectedly lower than MRR@10 ({bm25['MRR@10']:.4f})"
    )
