
import json
import os
import subprocess

import pytest


class TestDiagnosis:
    """Verify that the agent produced a substantive root-cause analysis."""

    def test_diagnosis_exists_and_nontrivial(self):
        assert os.path.exists("/app/diagnosis.txt"), "diagnosis.txt not found"
        with open("/app/diagnosis.txt") as f:
            text = f.read()
        assert len(text) > 200, (
            "Diagnosis is too short to be a meaningful root-cause analysis"
        )

    def test_diagnosis_covers_index_issue(self):
        """Diagnosis should identify the missing stored fields in the index."""
        if not os.path.exists("/app/diagnosis.txt"):
            pytest.skip("diagnosis.txt missing")
        with open("/app/diagnosis.txt") as f:
            text = f.read().lower()
        index_keywords = ["vector", "stored", "storedocvector", "raw", "storeraw"]
        matches = sum(1 for kw in index_keywords if kw in text)
        assert matches >= 2, (
            "Diagnosis should discuss the index storage configuration issue — "
            "expected mentions of document vectors and stored fields"
        )

    def test_diagnosis_covers_parameter_issue(self):
        """Diagnosis should identify the BM25 parameter discrepancy."""
        if not os.path.exists("/app/diagnosis.txt"):
            pytest.skip("diagnosis.txt missing")
        with open("/app/diagnosis.txt") as f:
            text = f.read().lower()
        param_indicators = ["k1", "0.9", "1.2", "parameter", "b=0.4", "b=0.75"]
        matches = sum(1 for kw in param_indicators if kw in text)
        assert matches >= 2, (
            "Diagnosis should discuss the BM25 parameter mismatch between "
            "what the log claims and what was actually used"
        )

    def test_diagnosis_covers_metrics_issue(self):
        """Diagnosis should identify the evaluation metrics discrepancy."""
        if not os.path.exists("/app/diagnosis.txt"):
            pytest.skip("diagnosis.txt missing")
        with open("/app/diagnosis.txt") as f:
            text = f.read().lower()
        metrics_keywords = ["0.6234", "0.7891", "metric", "report", "reproduce"]
        matches = sum(1 for kw in metrics_keywords if kw in text)
        assert matches >= 1, (
            "Diagnosis should discuss the evaluation metrics discrepancy"
        )


class TestIndexConstruction:
    """Verify the corrected Lucene index was built correctly."""

    def test_index_directory_exists(self):
        assert os.path.isdir("/app/index"), "Index directory /app/index does not exist"
        files = os.listdir("/app/index")
        assert len(files) > 0, "Index directory is empty"
        segment_files = [f for f in files if f.startswith("segments")]
        assert len(segment_files) > 0, "No Lucene segments file found in index"

    def test_index_has_60_documents(self):
        from pyserini.index.lucene import LuceneIndexReader

        reader = LuceneIndexReader("/app/index")
        stats = reader.stats()
        assert stats["documents"] == 60, (
            f"Expected 60 documents in index, got {stats['documents']}"
        )
        assert stats["non_empty_documents"] == 60, "Some documents in the index are empty"

    def test_index_supports_document_vectors(self):
        """The corrected index must support document vector extraction."""
        from pyserini.index.lucene import LuceneIndexReader

        if not os.path.isdir("/app/index"):
            pytest.skip("Index not built")

        reader = LuceneIndexReader("/app/index")
        doc_vector = reader.get_document_vector("doc001")
        assert doc_vector is not None, (
            "get_document_vector('doc001') returned None — index was likely "
            "built without --storeDocvectors"
        )
        assert len(doc_vector) > 0, "Document vector is empty"


class TestRunFiles:
    """Verify all run files exist and are in valid TREC format."""

    RUN_FILES = [
        "/app/runs/bm25_default.txt",
        "/app/runs/bm25_tuned.txt",
        "/app/runs/bm25_expanded.txt",
        "/app/runs/fused.txt",
    ]

    @pytest.mark.parametrize("run_file", RUN_FILES)
    def test_run_file_exists(self, run_file):
        assert os.path.exists(run_file), f"Missing run file: {run_file}"
        assert os.path.getsize(run_file) > 0, f"Run file is empty: {run_file}"

    @pytest.mark.parametrize("run_file", RUN_FILES)
    def test_run_file_trec_format(self, run_file):
        if not os.path.exists(run_file):
            pytest.skip(f"Run file missing: {run_file}")
        with open(run_file) as f:
            lines = f.readlines()
        assert len(lines) > 0, f"Empty run file: {run_file}"
        for i, line in enumerate(lines):
            parts = line.strip().split()
            assert len(parts) == 6, (
                f"Line {i+1} in {run_file} has {len(parts)} fields (expected 6): "
                f"{line.strip()}"
            )
            assert parts[1] == "Q0", (
                f"Second field should be 'Q0' on line {i+1} in {run_file}"
            )
            try:
                int(parts[3])
            except ValueError:
                pytest.fail(
                    f"Rank field (col 4) is not an integer on line {i+1} in {run_file}"
                )
            try:
                float(parts[4])
            except ValueError:
                pytest.fail(
                    f"Score field (col 5) is not numeric on line {i+1} in {run_file}"
                )

    def test_all_queries_present_in_default(self):
        """BM25 default run should have results for all 8 queries."""
        run_file = "/app/runs/bm25_default.txt"
        if not os.path.exists(run_file):
            pytest.skip("bm25_default.txt missing")
        query_ids = set()
        with open(run_file) as f:
            for line in f:
                query_ids.add(line.strip().split()[0])
        expected_qids = {str(i) for i in range(1, 9)}
        assert expected_qids.issubset(query_ids), (
            f"Missing query IDs in bm25_default.txt: {expected_qids - query_ids}"
        )


class TestBM25Correctness:
    """Independently verify BM25 retrieval results."""

    def test_bm25_default_top_docs(self):
        """Re-run BM25 default on query 1 and compare top-5 docids."""
        from pyserini.search.lucene import LuceneSearcher

        if not os.path.isdir("/app/index"):
            pytest.skip("Index not built")

        searcher = LuceneSearcher("/app/index")
        searcher.set_bm25(0.9, 0.4)

        # Read query 1 text
        query_text = None
        with open("/app/queries.tsv") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 2 and parts[0] == "1":
                    query_text = parts[1]
                    break
        assert query_text is not None, "Could not find query 1 in queries.tsv"

        hits = searcher.search(query_text, 10)
        expected_top5 = [hit.docid for hit in hits[:5]]

        # Parse agent's run file for query 1
        run_file = "/app/runs/bm25_default.txt"
        if not os.path.exists(run_file):
            pytest.skip("bm25_default.txt missing")
        agent_top5 = []
        with open(run_file) as f:
            for line in f:
                parts = line.strip().split()
                if parts[0] == "1":
                    agent_top5.append(parts[2])
                    if len(agent_top5) >= 5:
                        break

        assert agent_top5 == expected_top5, (
            f"BM25 default top-5 mismatch for query 1:\n"
            f"  agent:    {agent_top5}\n"
            f"  expected: {expected_top5}"
        )

    def test_bm25_tuned_differs_from_default(self):
        """Tuned BM25 should produce different scores than default."""
        if not os.path.exists("/app/runs/bm25_default.txt") or not os.path.exists(
            "/app/runs/bm25_tuned.txt"
        ):
            pytest.skip("Run files missing")

        def read_scores(path, qid="1"):
            scores = []
            with open(path) as f:
                for line in f:
                    parts = line.strip().split()
                    if parts[0] == qid:
                        scores.append(float(parts[4]))
            return scores

        default_scores = read_scores("/app/runs/bm25_default.txt")
        tuned_scores = read_scores("/app/runs/bm25_tuned.txt")

        # They should differ since parameters are different
        assert default_scores[:3] != tuned_scores[:3], (
            "BM25 default and tuned runs have identical scores for query 1 — "
            "parameters likely not applied"
        )

    def test_expanded_run_differs_from_default(self):
        """The expanded run should differ from default due to query expansion."""
        if not os.path.exists("/app/runs/bm25_default.txt") or not os.path.exists(
            "/app/runs/bm25_expanded.txt"
        ):
            pytest.skip("Run files missing")

        def read_docids(path, qid="1"):
            docids = []
            with open(path) as f:
                for line in f:
                    parts = line.strip().split()
                    if parts[0] == qid:
                        docids.append(parts[2])
            return docids

        default_docs = read_docids("/app/runs/bm25_default.txt")
        expanded_docs = read_docids("/app/runs/bm25_expanded.txt")

        # Rankings or scores should differ due to query expansion
        assert default_docs != expanded_docs, (
            "Expanded run has identical doc ranking to default for query 1 — "
            "query expansion may not be applied"
        )


class TestResultsJSON:
    """Verify results.json format and metric values."""

    def test_results_json_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_results_json_structure(self):
        if not os.path.exists("/app/results.json"):
            pytest.skip("results.json missing")
        with open("/app/results.json") as f:
            results = json.load(f)

        required_runs = ["bm25_default", "bm25_tuned", "bm25_expanded", "fused"]
        for run_name in required_runs:
            assert run_name in results, f"Missing '{run_name}' in results.json"
            assert "map" in results[run_name], f"Missing 'map' for {run_name}"
            assert "ndcg_cut_10" in results[run_name], (
                f"Missing 'ndcg_cut_10' for {run_name}"
            )
            map_val = results[run_name]["map"]
            ndcg_val = results[run_name]["ndcg_cut_10"]
            assert 0 <= map_val <= 1, f"MAP out of range for {run_name}: {map_val}"
            assert 0 <= ndcg_val <= 1, (
                f"nDCG@10 out of range for {run_name}: {ndcg_val}"
            )

    def test_results_default_metrics_match_trec_eval(self):
        """Re-run trec_eval on bm25_default.txt and verify metrics match results.json."""
        if not os.path.exists("/app/results.json") or not os.path.exists(
            "/app/runs/bm25_default.txt"
        ):
            pytest.skip("Required files missing")

        result = subprocess.run(
            [
                "python3",
                "-m",
                "pyserini.eval.trec_eval",
                "-m",
                "map",
                "-m",
                "ndcg_cut.10",
                "/app/qrels.txt",
                "/app/runs/bm25_default.txt",
            ],
            capture_output=True,
            text=True,
        )

        metrics = {}
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "all":
                metrics[parts[0]] = round(float(parts[2]), 4)

        with open("/app/results.json") as f:
            results = json.load(f)

        assert abs(results["bm25_default"]["map"] - metrics["map"]) < 0.001, (
            f"MAP mismatch: results.json={results['bm25_default']['map']}, "
            f"trec_eval={metrics['map']}"
        )
        assert abs(
            results["bm25_default"]["ndcg_cut_10"] - metrics["ndcg_cut_10"]
        ) < 0.001, (
            f"nDCG@10 mismatch: results.json="
            f"{results['bm25_default']['ndcg_cut_10']}, "
            f"trec_eval={metrics['ndcg_cut_10']}"
        )

    def test_results_fused_metrics_match_trec_eval(self):
        """Re-run trec_eval on fused.txt and verify metrics match results.json."""
        if not os.path.exists("/app/results.json") or not os.path.exists(
            "/app/runs/fused.txt"
        ):
            pytest.skip("Required files missing")

        result = subprocess.run(
            [
                "python3",
                "-m",
                "pyserini.eval.trec_eval",
                "-m",
                "map",
                "-m",
                "ndcg_cut.10",
                "/app/qrels.txt",
                "/app/runs/fused.txt",
            ],
            capture_output=True,
            text=True,
        )

        metrics = {}
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "all":
                metrics[parts[0]] = round(float(parts[2]), 4)

        with open("/app/results.json") as f:
            results = json.load(f)

        assert abs(results["fused"]["map"] - metrics["map"]) < 0.001, (
            f"Fused MAP mismatch: results.json={results['fused']['map']}, "
            f"trec_eval={metrics['map']}"
        )
        assert abs(
            results["fused"]["ndcg_cut_10"] - metrics["ndcg_cut_10"]
        ) < 0.001, (
            f"Fused nDCG@10 mismatch: results.json="
            f"{results['fused']['ndcg_cut_10']}, "
            f"trec_eval={metrics['ndcg_cut_10']}"
        )


class TestFusion:
    """Verify fusion output properties."""

    def test_fused_docs_come_from_input_runs(self):
        """Every document in the fused run must appear in at least one input run."""
        input_files = [
            "/app/runs/bm25_default.txt",
            "/app/runs/bm25_tuned.txt",
            "/app/runs/bm25_expanded.txt",
        ]
        fused_file = "/app/runs/fused.txt"

        for f in input_files + [fused_file]:
            if not os.path.exists(f):
                pytest.skip(f"Missing: {f}")

        input_docs = set()
        for run_file in input_files:
            with open(run_file) as f:
                for line in f:
                    parts = line.strip().split()
                    qid, docid = parts[0], parts[2]
                    input_docs.add((qid, docid))

        with open(fused_file) as f:
            for line in f:
                parts = line.strip().split()
                qid, docid = parts[0], parts[2]
                assert (qid, docid) in input_docs, (
                    f"Fused doc ({qid}, {docid}) not found in any input run"
                )

    def test_fused_run_has_all_queries(self):
        """Fused run should cover all 8 queries."""
        fused_file = "/app/runs/fused.txt"
        if not os.path.exists(fused_file):
            pytest.skip("fused.txt missing")
        query_ids = set()
        with open(fused_file) as f:
            for line in f:
                query_ids.add(line.strip().split()[0])
        expected_qids = {str(i) for i in range(1, 9)}
        assert expected_qids.issubset(query_ids), (
            f"Missing query IDs in fused.txt: {expected_qids - query_ids}"
        )


class TestTermAnalysis:
    """Verify term analysis output."""

    def test_term_analysis_exists(self):
        assert os.path.exists("/app/term_analysis.json"), "term_analysis.json not found"

    def test_term_analysis_structure(self):
        if not os.path.exists("/app/term_analysis.json"):
            pytest.skip("term_analysis.json missing")
        with open("/app/term_analysis.json") as f:
            analysis = json.load(f)

        assert len(analysis) > 0, "term_analysis.json is empty"
        for qid, data in analysis.items():
            assert "top_doc" in data, f"Missing 'top_doc' for query {qid}"
            assert "top_terms" in data, f"Missing 'top_terms' for query {qid}"
            assert len(data["top_terms"]) > 0, f"No terms for query {qid}"
            assert len(data["top_terms"]) <= 5, (
                f"More than 5 terms for query {qid}"
            )
            for entry in data["top_terms"]:
                assert "term" in entry, "Missing 'term' in top_terms entry"
                assert "weight" in entry, "Missing 'weight' in top_terms entry"
                assert isinstance(entry["weight"], (int, float)), (
                    f"Weight is not numeric for term '{entry.get('term')}'"
                )
                assert entry["weight"] > 0, (
                    f"Non-positive BM25 weight for term '{entry['term']}'"
                )

    def test_term_analysis_top_doc_matches_run(self):
        """Top doc in analysis should match top doc in bm25_default run."""
        if not os.path.exists("/app/term_analysis.json") or not os.path.exists(
            "/app/runs/bm25_default.txt"
        ):
            pytest.skip("Required files missing")

        # Get top doc per query from bm25_default run
        run_top_docs = {}
        with open("/app/runs/bm25_default.txt") as f:
            for line in f:
                parts = line.strip().split()
                qid = parts[0]
                if qid not in run_top_docs:
                    run_top_docs[qid] = parts[2]

        with open("/app/term_analysis.json") as f:
            analysis = json.load(f)

        for qid, data in analysis.items():
            if qid in run_top_docs:
                assert data["top_doc"] == run_top_docs[qid], (
                    f"Query {qid}: top_doc in analysis ({data['top_doc']}) "
                    f"doesn't match top doc in bm25_default ({run_top_docs[qid]})"
                )

    def test_term_analysis_bm25_weight_correctness(self):
        """Spot-check BM25 term weight by independent computation."""
        if not os.path.exists("/app/term_analysis.json") or not os.path.isdir(
            "/app/index"
        ):
            pytest.skip("Required files missing")

        from pyserini.index.lucene import LuceneIndexReader

        with open("/app/term_analysis.json") as f:
            analysis = json.load(f)

        reader = LuceneIndexReader("/app/index")

        # Check first query entry
        for qid in sorted(analysis.keys()):
            data = analysis[qid]
            top_doc = data["top_doc"]
            if len(data["top_terms"]) == 0:
                continue

            doc_vector = reader.get_document_vector(top_doc)
            assert doc_vector is not None, (
                f"Could not get document vector for {top_doc}"
            )

            term = data["top_terms"][0]["term"]
            reported_weight = data["top_terms"][0]["weight"]

            # Term from analysis should be an analyzed term from the doc vector
            assert term in doc_vector, (
                f"Term '{term}' not found in document vector of {top_doc}. "
                f"Available terms (first 10): {list(doc_vector.keys())[:10]}"
            )

            # Independently compute BM25 weight using analyzer=None
            # (since term is already analyzed)
            actual_weight = reader.compute_bm25_term_weight(
                top_doc, term, analyzer=None
            )
            assert abs(reported_weight - actual_weight) < 0.02, (
                f"BM25 weight mismatch for term '{term}' in doc '{top_doc}': "
                f"reported={reported_weight}, actual={actual_weight}"
            )
            break  # Only check the first query
