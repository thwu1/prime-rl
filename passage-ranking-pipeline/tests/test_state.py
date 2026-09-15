"""Tests for the passage ranking evaluation pipeline task.

Verifies: fixed eval script correctness, BM25 run format and quality,
and submission package validity.
"""

import os
import json
import subprocess
import bz2
import re
import pytest


def compute_correct_mrr10(qrels_path, run_path):
    """Independent correct MRR@10 implementation for verification."""
    # Load qrels (TREC format: QID  0  PID  Relevance)
    qrels = {}
    with open(qrels_path) as f:
        for line in f:
            parts = line.strip().split('\t')
            qid = int(parts[0])
            pid = int(parts[2])
            if qid not in qrels:
                qrels[qid] = []
            qrels[qid].append(pid)

    # Load run (MS MARCO format: QID  PID  Rank)
    run = {}
    with open(run_path) as f:
        for line in f:
            parts = line.strip().split('\t')
            qid = int(parts[0])
            pid = int(parts[1])
            rank = int(parts[2])
            if qid not in run:
                run[qid] = [0] * 1000
            run[qid][rank - 1] = pid

    # Compute MRR@10
    mrr = 0.0
    for qid in run:
        if qid in qrels:
            for i in range(10):
                if run[qid][i] in qrels[qid]:
                    mrr += 1.0 / (i + 1)
                    break

    return mrr / len(qrels)


class TestFixedEvalScript:
    """Test that the fixed evaluation script produces correct MRR@10 scores."""

    def test_fixed_eval_exists(self):
        assert os.path.exists("/app/eval/ms_marco_eval_fixed.py"), \
            "Fixed eval script not found at /app/eval/ms_marco_eval_fixed.py"

    @pytest.mark.parametrize("run_name", ["random_run", "oracle_run", "partial_run"])
    def test_reference_scores(self, run_name):
        """Fixed eval must reproduce reference MRR@10 scores."""
        with open("/app/eval/reference_scores.json") as f:
            ref_scores = json.load(f)

        expected = ref_scores[run_name]

        result = subprocess.run(
            ["python3", "/app/eval/ms_marco_eval_fixed.py",
             "/app/data/qrels.tsv",
             f"/app/eval/reference_runs/{run_name}.tsv"],
            capture_output=True, text=True, timeout=30
        )

        assert result.returncode == 0, \
            f"Fixed eval script failed on {run_name}: {result.stderr}"

        match = re.search(r'MRR @10:\s*([\d.eE\-+]+)', result.stdout)
        assert match, \
            f"Could not parse MRR @10 from output: {result.stdout}"

        actual = float(match.group(1))
        assert abs(actual - expected) < 0.0001, \
            f"MRR mismatch for {run_name}: expected {expected:.6f}, got {actual:.6f}"

    def test_oracle_mrr_is_one(self):
        """Oracle run (relevant always at rank 1) must have MRR@10 = 1.0."""
        with open("/app/eval/reference_scores.json") as f:
            ref_scores = json.load(f)
        assert abs(ref_scores["oracle_run"] - 1.0) < 0.0001, \
            f"Oracle reference MRR should be 1.0, got {ref_scores['oracle_run']}"


class TestBM25Run:
    """Test the BM25 reranking run file."""

    def test_run_file_exists(self):
        assert os.path.exists("/app/output/run.tsv"), \
            "Run file not found at /app/output/run.tsv"

    def test_run_format(self):
        """Run file must be QID\\tPID\\tRANK with integer fields."""
        with open("/app/output/run.tsv") as f:
            lines = f.readlines()

        assert len(lines) > 0, "Run file is empty"

        seen_qids = set()
        for i, line in enumerate(lines):
            parts = line.strip().split('\t')
            assert len(parts) == 3, \
                f"Line {i+1}: expected 3 tab-separated fields, got {len(parts)}"
            try:
                qid = int(parts[0])
                pid = int(parts[1])
                rank = int(parts[2])
            except ValueError:
                pytest.fail(f"Line {i+1}: all fields must be integers, got {parts}")
            assert rank >= 1, f"Line {i+1}: rank must be >= 1, got {rank}"
            seen_qids.add(qid)

        assert len(seen_qids) >= 30, \
            f"Expected >= 30 queries in run, got {len(seen_qids)}"

    def test_ranks_are_contiguous(self):
        """For each query, ranks should be contiguous starting from 1."""
        qid_ranks = {}
        with open("/app/output/run.tsv") as f:
            for line in f:
                parts = line.strip().split('\t')
                qid = int(parts[0])
                rank = int(parts[2])
                if qid not in qid_ranks:
                    qid_ranks[qid] = []
                qid_ranks[qid].append(rank)

        for qid, ranks in qid_ranks.items():
            sorted_ranks = sorted(ranks)
            expected = list(range(1, len(ranks) + 1))
            assert sorted_ranks == expected, \
                f"QID {qid}: ranks not contiguous 1..{len(ranks)}"

    def test_no_duplicate_pids_per_query(self):
        """Each query must not have duplicate passage IDs."""
        qid_pids = {}
        with open("/app/output/run.tsv") as f:
            for line in f:
                parts = line.strip().split('\t')
                qid = int(parts[0])
                pid = int(parts[1])
                if qid not in qid_pids:
                    qid_pids[qid] = set()
                assert pid not in qid_pids[qid], \
                    f"QID {qid}: duplicate PID {pid}"
                qid_pids[qid].add(pid)

    def test_mrr_threshold(self):
        """BM25 run must achieve MRR@10 >= 0.28."""
        mrr = compute_correct_mrr10("/app/data/qrels.tsv", "/app/output/run.tsv")
        assert mrr >= 0.28, f"MRR@10 = {mrr:.4f}, required >= 0.28"


class TestSubmissionPackage:
    """Test the submission package."""

    def test_metadata_exists(self):
        assert os.path.exists("/app/output/submission/metadata.json"), \
            "metadata.json not found at /app/output/submission/metadata.json"

    def test_metadata_fields(self):
        """Metadata must have all required fields with valid values."""
        with open("/app/output/submission/metadata.json") as f:
            metadata = json.load(f)

        required = ["team", "model_description", "paper", "code", "type"]
        for field in required:
            assert field in metadata, f"Missing required field: {field}"

        assert metadata["type"] in ["full ranking", "reranking"], \
            f"type must be 'full ranking' or 'reranking', got '{metadata['type']}'"

    def test_bz2_exists(self):
        assert os.path.exists("/app/output/submission/dev.txt.bz2"), \
            "dev.txt.bz2 not found at /app/output/submission/dev.txt.bz2"

    def test_bz2_decompresses_to_valid_run(self):
        """Compressed file must decompress to valid run data."""
        with bz2.open("/app/output/submission/dev.txt.bz2", "rt") as f:
            lines = f.readlines()

        assert len(lines) > 0, "Decompressed file is empty"

        parts = lines[0].strip().split('\t')
        assert len(parts) == 3, \
            f"Decompressed data has wrong format: expected 3 fields, got {len(parts)}"

    def test_bz2_matches_run(self):
        """Compressed file content must match run.tsv exactly."""
        with open("/app/output/run.tsv") as f:
            run_content = f.read()

        with bz2.open("/app/output/submission/dev.txt.bz2", "rt") as f:
            bz2_content = f.read()

        assert run_content == bz2_content, \
            "dev.txt.bz2 content does not match run.tsv"
