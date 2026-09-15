#!/usr/bin/env python3
"""Tests for Clinical NLP Evaluation Engine."""

import json
import os
import shutil
import subprocess
import tempfile

import pytest

GOLD_DIR = "/app/data/gold_brat"
SYS_DIR = "/app/data/system_brat"
GOLD_XML_DIR = "/app/data/gold_xml"
SYS_XML_DIR = "/app/data/system_xml"
EVAL_SCRIPT = "/app/clinical_eval/evaluate.py"


def run_eval(gold_dir, sys_dir, matching="strict", threshold=0.5):
    """Run the evaluation CLI and return parsed JSON."""
    fd, output_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        cmd = [
            "python3", EVAL_SCRIPT,
            "--gold", gold_dir,
            "--system", sys_dir,
            "--matching", matching,
            "--threshold", str(threshold),
            "--output", output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, (
            f"CLI exited {result.returncode}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        with open(output_path) as f:
            return json.load(f)
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def make_single_doc_dirs(doc_id):
    """Copy a single document into temp gold/system dirs."""
    gold = tempfile.mkdtemp()
    sys = tempfile.mkdtemp()
    for ext in (".txt", ".ann"):
        src_g = os.path.join(GOLD_DIR, doc_id + ext)
        src_s = os.path.join(SYS_DIR, doc_id + ext)
        if os.path.exists(src_g):
            shutil.copy(src_g, gold)
        if os.path.exists(src_s):
            shutil.copy(src_s, sys)
    return gold, sys


# ─── Output structure ───────────────────────────────────────────────


class TestOutputStructure:
    def test_required_top_level_keys(self):
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        for key in ("matching_mode", "threshold", "entity_metrics",
                     "relation_metrics", "attribute_metrics", "micro", "macro",
                     "per_document"):
            assert key in r, f"Missing key: {key}"

    def test_matching_mode_echoed(self):
        for mode in ("strict", "overlap", "type"):
            r = run_eval(GOLD_DIR, SYS_DIR, mode)
            assert r["matching_mode"] == mode

    def test_entity_metric_fields(self):
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        for etype, m in r["entity_metrics"].items():
            for field in ("precision", "recall", "f1", "tp", "fp", "fn"):
                assert field in m, f"{etype} missing {field}"

    def test_micro_macro_fields(self):
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        for agg in ("micro", "macro"):
            for field in ("precision", "recall", "f1"):
                assert field in r[agg], f"{agg} missing {field}"


# ─── doc001 strict entity matching ──────────────────────────────────


class TestDoc001Strict:
    @pytest.fixture(autouse=True)
    def _dirs(self):
        self.g, self.s = make_single_doc_dirs("doc001")
        yield
        shutil.rmtree(self.g, ignore_errors=True)
        shutil.rmtree(self.s, ignore_errors=True)

    def test_drug_perfect(self):
        r = run_eval(self.g, self.s, "strict")
        d = r["entity_metrics"]["Drug"]
        assert d["tp"] == 1 and d["fp"] == 0 and d["fn"] == 0

    def test_dosage_perfect(self):
        r = run_eval(self.g, self.s, "strict")
        d = r["entity_metrics"]["Dosage"]
        assert d["tp"] == 1 and d["fp"] == 0 and d["fn"] == 0

    def test_frequency_missed(self):
        r = run_eval(self.g, self.s, "strict")
        d = r["entity_metrics"]["Frequency"]
        assert d["tp"] == 0 and d["fn"] == 1
        assert abs(d["f1"]) < 1e-9

    def test_ade_off_by_one_fails_strict(self):
        r = run_eval(self.g, self.s, "strict")
        d = r["entity_metrics"]["ADE"]
        assert d["tp"] == 0 and d["fp"] == 1 and d["fn"] == 1

    def test_micro(self):
        r = run_eval(self.g, self.s, "strict")
        assert abs(r["micro"]["precision"] - 2 / 3) < 1e-6
        assert abs(r["micro"]["recall"] - 0.5) < 1e-6
        assert abs(r["micro"]["f1"] - 4 / 7) < 1e-6

    def test_macro_f1(self):
        r = run_eval(self.g, self.s, "strict")
        # Drug 1.0, Dosage 1.0, Frequency 0.0, ADE 0.0 → 0.5
        assert abs(r["macro"]["f1"] - 0.5) < 1e-6


# ─── doc001 overlap entity matching ─────────────────────────────────


class TestDoc001Overlap:
    @pytest.fixture(autouse=True)
    def _dirs(self):
        self.g, self.s = make_single_doc_dirs("doc001")
        yield
        shutil.rmtree(self.g, ignore_errors=True)
        shutil.rmtree(self.s, ignore_errors=True)

    def test_ade_matches_with_overlap(self):
        """28:35 vs 29:35 → IoU = 6/7 ≈ 0.857 ≥ 0.5."""
        r = run_eval(self.g, self.s, "overlap", 0.5)
        d = r["entity_metrics"]["ADE"]
        assert d["tp"] == 1 and d["fp"] == 0 and d["fn"] == 0

    def test_ade_fails_high_threshold(self):
        """IoU ≈ 0.857 < 0.9 → no match."""
        r = run_eval(self.g, self.s, "overlap", 0.9)
        assert r["entity_metrics"]["ADE"]["tp"] == 0

    def test_micro_overlap(self):
        r = run_eval(self.g, self.s, "overlap", 0.5)
        assert abs(r["micro"]["precision"] - 1.0) < 1e-6
        assert abs(r["micro"]["recall"] - 0.75) < 1e-6
        assert abs(r["micro"]["f1"] - 6 / 7) < 1e-6

    def test_macro_overlap(self):
        r = run_eval(self.g, self.s, "overlap", 0.5)
        # Drug 1.0, Dosage 1.0, Frequency 0.0, ADE 1.0 → 0.75
        assert abs(r["macro"]["f1"] - 0.75) < 1e-6


# ─── Type matching mode ─────────────────────────────────────────────


class TestTypeMatching:
    def test_doc001_ade_matches_in_type_mode(self):
        """In type mode, ADE(29:35) vs ADE(28:35) matches (overlap >= 1)."""
        g, s = make_single_doc_dirs("doc001")
        try:
            r = run_eval(g, s, "type")
            d = r["entity_metrics"]["ADE"]
            assert d["tp"] == 1 and d["fp"] == 0 and d["fn"] == 0
        finally:
            shutil.rmtree(g, ignore_errors=True)
            shutil.rmtree(s, ignore_errors=True)

    def test_doc001_type_micro(self):
        """doc001 type mode: Drug TP, Dosage TP, ADE TP, Frequency FN.
        micro P=3/3=1.0, R=3/4=0.75, F1=6/7."""
        g, s = make_single_doc_dirs("doc001")
        try:
            r = run_eval(g, s, "type")
            assert abs(r["micro"]["precision"] - 1.0) < 1e-6
            assert abs(r["micro"]["recall"] - 0.75) < 1e-6
            assert abs(r["micro"]["f1"] - 6 / 7) < 1e-6
        finally:
            shutil.rmtree(g, ignore_errors=True)
            shutil.rmtree(s, ignore_errors=True)

    def test_minimal_overlap_matches_type_but_not_overlap(self):
        """Entities sharing exactly 1 character: type mode matches, overlap
        mode at threshold 0.5 does not (IoU = 1/199 ≈ 0.005 < 0.5)."""
        g_dir = tempfile.mkdtemp()
        s_dir = tempfile.mkdtemp()
        try:
            text = "a" * 200
            for d in (g_dir, s_dir):
                with open(os.path.join(d, "min.txt"), "w") as f:
                    f.write(text)

            with open(os.path.join(g_dir, "min.ann"), "w") as f:
                f.write("T1\tDrug 0 100\t" + "a" * 100 + "\n")

            with open(os.path.join(s_dir, "min.ann"), "w") as f:
                f.write("T1\tDrug 99 200\t" + "a" * 101 + "\n")

            # overlap mode at threshold 0.5 should NOT match (IoU = 1/200)
            r_overlap = run_eval(g_dir, s_dir, "overlap", 0.5)
            assert r_overlap["entity_metrics"]["Drug"]["tp"] == 0
            assert r_overlap["entity_metrics"]["Drug"]["fp"] == 1
            assert r_overlap["entity_metrics"]["Drug"]["fn"] == 1

            # type mode SHOULD match (overlap >= 1 char)
            r_type = run_eval(g_dir, s_dir, "type")
            assert r_type["entity_metrics"]["Drug"]["tp"] == 1
            assert r_type["entity_metrics"]["Drug"]["fp"] == 0
            assert r_type["entity_metrics"]["Drug"]["fn"] == 0
        finally:
            shutil.rmtree(g_dir, ignore_errors=True)
            shutil.rmtree(s_dir, ignore_errors=True)

    def test_no_overlap_no_match_in_type_mode(self):
        """Entities of same type with zero character overlap: no match
        even in type mode."""
        g_dir = tempfile.mkdtemp()
        s_dir = tempfile.mkdtemp()
        try:
            text = "a" * 200
            for d in (g_dir, s_dir):
                with open(os.path.join(d, "nop.txt"), "w") as f:
                    f.write(text)

            with open(os.path.join(g_dir, "nop.ann"), "w") as f:
                f.write("T1\tDrug 0 50\t" + "a" * 50 + "\n")

            with open(os.path.join(s_dir, "nop.ann"), "w") as f:
                f.write("T1\tDrug 100 150\t" + "a" * 50 + "\n")

            r = run_eval(g_dir, s_dir, "type")
            assert r["entity_metrics"]["Drug"]["tp"] == 0
            assert r["entity_metrics"]["Drug"]["fp"] == 1
            assert r["entity_metrics"]["Drug"]["fn"] == 1
        finally:
            shutil.rmtree(g_dir, ignore_errors=True)
            shutil.rmtree(s_dir, ignore_errors=True)

    def test_type_ignores_threshold_parameter(self):
        """Type mode matches on any overlap >= 1, regardless of --threshold."""
        g_dir = tempfile.mkdtemp()
        s_dir = tempfile.mkdtemp()
        try:
            text = "a" * 200
            for d in (g_dir, s_dir):
                with open(os.path.join(d, "thr.txt"), "w") as f:
                    f.write(text)

            with open(os.path.join(g_dir, "thr.ann"), "w") as f:
                f.write("T1\tDrug 0 100\t" + "a" * 100 + "\n")

            with open(os.path.join(s_dir, "thr.ann"), "w") as f:
                f.write("T1\tDrug 99 200\t" + "a" * 101 + "\n")

            # Even with threshold 0.99, type mode matches on any overlap
            r = run_eval(g_dir, s_dir, "type", 0.99)
            assert r["entity_metrics"]["Drug"]["tp"] == 1
        finally:
            shutil.rmtree(g_dir, ignore_errors=True)
            shutil.rmtree(s_dir, ignore_errors=True)


# ─── doc001 relation evaluation ─────────────────────────────────────


class TestDoc001Relations:
    @pytest.fixture(autouse=True)
    def _dirs(self):
        self.g, self.s = make_single_doc_dirs("doc001")
        yield
        shutil.rmtree(self.g, ignore_errors=True)
        shutil.rmtree(self.s, ignore_errors=True)

    def test_dosage_drug_strict(self):
        r = run_eval(self.g, self.s, "strict")
        d = r["relation_metrics"]["Dosage-Drug"]
        assert d["tp"] == 1 and d["fp"] == 0 and d["fn"] == 0

    def test_frequency_drug_missed_strict(self):
        r = run_eval(self.g, self.s, "strict")
        d = r["relation_metrics"]["Frequency-Drug"]
        assert d["tp"] == 0 and d["fn"] == 1

    def test_ade_drug_strict_unmatched(self):
        r = run_eval(self.g, self.s, "strict")
        d = r["relation_metrics"]["ADE-Drug"]
        assert d["tp"] == 0 and d["fp"] == 1 and d["fn"] == 1

    def test_ade_drug_overlap_matches(self):
        r = run_eval(self.g, self.s, "overlap", 0.5)
        d = r["relation_metrics"]["ADE-Drug"]
        assert d["tp"] == 1 and d["fp"] == 0 and d["fn"] == 0


# ─── doc001 attribute evaluation ────────────────────────────────────


class TestDoc001Attributes:
    @pytest.fixture(autouse=True)
    def _dirs(self):
        self.g, self.s = make_single_doc_dirs("doc001")
        yield
        shutil.rmtree(self.g, ignore_errors=True)
        shutil.rmtree(self.s, ignore_errors=True)

    def test_strict_attribute_accuracy(self):
        r = run_eval(self.g, self.s, "strict")
        a = r["attribute_metrics"]["Assertion"]
        # Only Drug matched → 1 evaluated, correct (present == present)
        assert a["correct"] == 1 and a["total"] == 1
        assert abs(a["accuracy"] - 1.0) < 1e-9

    def test_overlap_attribute_accuracy(self):
        r = run_eval(self.g, self.s, "overlap", 0.5)
        a = r["attribute_metrics"]["Assertion"]
        # Drug + ADE matched → 2 evaluated; Drug correct, ADE wrong (present vs absent)
        assert a["correct"] == 1 and a["total"] == 2
        assert abs(a["accuracy"] - 0.5) < 1e-9


# ─── doc003 discontinuous entities ──────────────────────────────────


class TestDoc003Discontinuous:
    @pytest.fixture(autouse=True)
    def _dirs(self):
        self.g, self.s = make_single_doc_dirs("doc003")
        yield
        shutil.rmtree(self.g, ignore_errors=True)
        shutil.rmtree(self.s, ignore_errors=True)

    def test_strict_no_match(self):
        r = run_eval(self.g, self.s, "strict")
        d = r["entity_metrics"]["Finding"]
        assert d["tp"] == 0 and d["fp"] == 1 and d["fn"] == 2

    def test_overlap_one_match(self):
        """System entity overlaps both golds; optimal assignment picks one."""
        r = run_eval(self.g, self.s, "overlap", 0.5)
        d = r["entity_metrics"]["Finding"]
        assert d["tp"] == 1 and d["fp"] == 0 and d["fn"] == 1

    def test_overlap_f1(self):
        r = run_eval(self.g, self.s, "overlap", 0.5)
        # P=1/1=1.0, R=1/2=0.5, F1=2/3
        assert abs(r["entity_metrics"]["Finding"]["f1"] - 2 / 3) < 1e-6


# ─── doc004 empty annotations ──────────────────────────────────────


class TestDoc004Empty:
    @pytest.fixture(autouse=True)
    def _dirs(self):
        self.g, self.s = make_single_doc_dirs("doc004")
        yield
        shutil.rmtree(self.g, ignore_errors=True)
        shutil.rmtree(self.s, ignore_errors=True)

    def test_no_entity_types(self):
        r = run_eval(self.g, self.s, "strict")
        assert r["entity_metrics"] == {}

    def test_no_relation_types(self):
        r = run_eval(self.g, self.s, "strict")
        assert r["relation_metrics"] == {}

    def test_zero_micro(self):
        r = run_eval(self.g, self.s, "strict")
        assert abs(r["micro"]["f1"]) < 1e-9

    def test_zero_macro(self):
        r = run_eval(self.g, self.s, "strict")
        assert abs(r["macro"]["f1"]) < 1e-9


# ─── Cross-format evaluation ───────────────────────────────────────


class TestCrossFormat:
    def test_brat_gold_xml_system_strict(self):
        """Gold brat doc001 vs system XML doc001 → same metrics as brat-brat."""
        g_brat, s_brat = make_single_doc_dirs("doc001")
        try:
            r_brat = run_eval(g_brat, s_brat, "strict")
        finally:
            shutil.rmtree(g_brat, ignore_errors=True)
            shutil.rmtree(s_brat, ignore_errors=True)

        # Gold brat, system XML
        g_dir = tempfile.mkdtemp()
        s_dir = tempfile.mkdtemp()
        try:
            shutil.copy(os.path.join(GOLD_DIR, "doc001.txt"), g_dir)
            shutil.copy(os.path.join(GOLD_DIR, "doc001.ann"), g_dir)
            shutil.copy(os.path.join(SYS_XML_DIR, "doc001.xml"), s_dir)

            r_cross = run_eval(g_dir, s_dir, "strict")
            assert abs(r_cross["micro"]["f1"] - r_brat["micro"]["f1"]) < 1e-6
        finally:
            shutil.rmtree(g_dir, ignore_errors=True)
            shutil.rmtree(s_dir, ignore_errors=True)

    def test_xml_gold_brat_system_overlap(self):
        """XML gold doc001 vs brat system doc001."""
        g_dir = tempfile.mkdtemp()
        s_dir = tempfile.mkdtemp()
        try:
            shutil.copy(os.path.join(GOLD_XML_DIR, "doc001.xml"), g_dir)
            shutil.copy(os.path.join(SYS_DIR, "doc001.txt"), s_dir)
            shutil.copy(os.path.join(SYS_DIR, "doc001.ann"), s_dir)

            r = run_eval(g_dir, s_dir, "overlap", 0.5)
            # Same as brat-brat overlap: micro F1 = 6/7
            assert abs(r["micro"]["f1"] - 6 / 7) < 1e-6
        finally:
            shutil.rmtree(g_dir, ignore_errors=True)
            shutil.rmtree(s_dir, ignore_errors=True)


# ─── Full corpus aggregation ───────────────────────────────────────


class TestFullCorpus:
    def test_strict_micro(self):
        """Across 5 docs: TP=10, FP=5, FN=7 → P=2/3, R=10/17, F1=5/8."""
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        assert abs(r["micro"]["precision"] - 2 / 3) < 1e-4
        assert abs(r["micro"]["recall"] - 10 / 17) < 1e-4
        assert abs(r["micro"]["f1"] - 5 / 8) < 1e-4

    def test_overlap_micro(self):
        """Across 5 docs: TP=15, FP=0, FN=2 → P=1.0, R=15/17, F1=15/16."""
        r = run_eval(GOLD_DIR, SYS_DIR, "overlap", 0.5)
        assert abs(r["micro"]["precision"] - 1.0) < 1e-4
        assert abs(r["micro"]["recall"] - 15 / 17) < 1e-4
        assert abs(r["micro"]["f1"] - 15 / 16) < 1e-4

    def test_strict_all_entity_types_present(self):
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        expected = {"Drug", "Dosage", "Frequency", "ADE", "Reason", "Finding"}
        assert set(r["entity_metrics"].keys()) == expected

    def test_strict_drug_counts(self):
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        d = r["entity_metrics"]["Drug"]
        assert d["tp"] == 4 and d["fp"] == 1 and d["fn"] == 1

    def test_overlap_drug_perfect(self):
        r = run_eval(GOLD_DIR, SYS_DIR, "overlap", 0.5)
        d = r["entity_metrics"]["Drug"]
        assert d["tp"] == 5 and d["fp"] == 0 and d["fn"] == 0


# ─── Optimal matching constraint ───────────────────────────────────


class TestOptimalMatching:
    def test_one_system_entity_matches_at_most_one_gold(self):
        """Synthetic: 2 golds + 1 system all overlap. TP must be exactly 1."""
        g_dir = tempfile.mkdtemp()
        s_dir = tempfile.mkdtemp()
        try:
            text = "abcdefghijklmnopqrstuvwxyz0123456789"
            for d in (g_dir, s_dir):
                with open(os.path.join(d, "synth.txt"), "w") as f:
                    f.write(text)

            with open(os.path.join(g_dir, "synth.ann"), "w") as f:
                f.write("T1\tX 0 15\tabcdefghijklmno\n")
                f.write("T2\tX 10 25\tklmnopqrstuvwxy\n")

            with open(os.path.join(s_dir, "synth.ann"), "w") as f:
                f.write("T1\tX 5 20\tfghijklmnopqrst\n")

            r = run_eval(g_dir, s_dir, "overlap", 0.3)
            assert r["entity_metrics"]["X"]["tp"] == 1
            assert r["entity_metrics"]["X"]["fp"] == 0
            assert r["entity_metrics"]["X"]["fn"] == 1
        finally:
            shutil.rmtree(g_dir, ignore_errors=True)
            shutil.rmtree(s_dir, ignore_errors=True)


# ─── doc005 overlap (multi-entity, relation chain) ──────────────────


class TestDoc005Overlap:
    @pytest.fixture(autouse=True)
    def _dirs(self):
        self.g, self.s = make_single_doc_dirs("doc005")
        yield
        shutil.rmtree(self.g, ignore_errors=True)
        shutil.rmtree(self.s, ignore_errors=True)

    def test_all_entities_match(self):
        r = run_eval(self.g, self.s, "overlap", 0.5)
        for etype in ("Drug", "Dosage", "Frequency", "ADE"):
            assert r["entity_metrics"][etype]["fn"] == 0, f"{etype} has false negatives"

    def test_all_relations_match(self):
        r = run_eval(self.g, self.s, "overlap", 0.5)
        for rtype in ("Dosage-Drug", "Frequency-Drug", "ADE-Drug"):
            assert r["relation_metrics"][rtype]["tp"] > 0, f"{rtype} has no true positives"
            assert r["relation_metrics"][rtype]["fn"] == 0, f"{rtype} has false negatives"

    def test_doc005_strict_drug_partial(self):
        r = run_eval(self.g, self.s, "strict")
        d = r["entity_metrics"]["Drug"]
        # One drug exact, one off-by-one → TP=1, FP=1, FN=1
        assert d["tp"] == 1 and d["fp"] == 1 and d["fn"] == 1


# ─── Per-document metrics ──────────────────────────────────────────


class TestPerDocumentMetrics:
    def test_per_document_key_present(self):
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        assert "per_document" in r
        assert isinstance(r["per_document"], dict)

    def test_per_document_has_all_docs(self):
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        for doc_id in ("doc001", "doc002", "doc003", "doc004", "doc005"):
            assert doc_id in r["per_document"], f"Missing per_document entry: {doc_id}"

    def test_per_document_structure(self):
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        for doc_id, doc_metrics in r["per_document"].items():
            for key in ("entity_metrics", "relation_metrics",
                        "attribute_metrics", "micro", "macro"):
                assert key in doc_metrics, f"{doc_id} missing {key}"

    def test_per_document_doc001_strict_micro(self):
        """Per-document metrics for doc001 must match single-doc evaluation."""
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        doc_r = r["per_document"]["doc001"]
        # doc001 strict: TP=2, FP=1, FN=2 → P=2/3, R=0.5
        assert abs(doc_r["micro"]["precision"] - 2 / 3) < 1e-6
        assert abs(doc_r["micro"]["recall"] - 0.5) < 1e-6
        assert abs(doc_r["micro"]["f1"] - 4 / 7) < 1e-6

    def test_per_document_doc004_empty(self):
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        doc_r = r["per_document"]["doc004"]
        assert doc_r["entity_metrics"] == {}
        assert abs(doc_r["micro"]["f1"]) < 1e-9

    def test_per_document_tp_sum_matches_aggregate(self):
        """Sum of per-doc TP for each type must equal aggregate TP."""
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        for etype in r["entity_metrics"]:
            agg_tp = r["entity_metrics"][etype]["tp"]
            doc_tp_sum = sum(
                doc_r["entity_metrics"].get(etype, {}).get("tp", 0)
                for doc_r in r["per_document"].values()
            )
            assert agg_tp == doc_tp_sum, (
                f"{etype}: agg TP={agg_tp}, sum doc TP={doc_tp_sum}"
            )

    def test_per_document_fp_fn_sum_matches_aggregate(self):
        """Sum of per-doc FP/FN for each type must equal aggregate FP/FN."""
        r = run_eval(GOLD_DIR, SYS_DIR, "overlap", 0.5)
        for etype in r["entity_metrics"]:
            for metric in ("fp", "fn"):
                agg_val = r["entity_metrics"][etype][metric]
                doc_sum = sum(
                    doc_r["entity_metrics"].get(etype, {}).get(metric, 0)
                    for doc_r in r["per_document"].values()
                )
                assert agg_val == doc_sum, (
                    f"{etype} {metric}: agg={agg_val}, sum={doc_sum}"
                )

    def test_per_document_doc005_overlap_drug(self):
        """Per-document doc005 overlap should show all drugs matched."""
        r = run_eval(GOLD_DIR, SYS_DIR, "overlap", 0.5)
        d5 = r["per_document"]["doc005"]
        assert d5["entity_metrics"]["Drug"]["tp"] == 2
        assert d5["entity_metrics"]["Drug"]["fn"] == 0

    def test_per_document_doc003_strict_finding(self):
        """Per-document doc003 strict: no Finding matches (discontinuous)."""
        r = run_eval(GOLD_DIR, SYS_DIR, "strict")
        d3 = r["per_document"]["doc003"]
        assert d3["entity_metrics"]["Finding"]["tp"] == 0
        assert d3["entity_metrics"]["Finding"]["fp"] == 1
        assert d3["entity_metrics"]["Finding"]["fn"] == 2


# ─── Document-set asymmetry ────────────────────────────────────────


class TestDocumentSetAsymmetry:
    def test_gold_only_doc_contributes_fn(self):
        """A document in gold but not system → all entities are FN."""
        g_dir = tempfile.mkdtemp()
        s_dir = tempfile.mkdtemp()
        try:
            with open(os.path.join(g_dir, "a.txt"), "w") as f:
                f.write("Aspirin 81mg daily")
            with open(os.path.join(g_dir, "a.ann"), "w") as f:
                f.write("T1\tDrug 0 7\tAspirin\nT2\tDosage 8 12\t81mg\n")
            # System has a different doc with no entities
            with open(os.path.join(s_dir, "b.txt"), "w") as f:
                f.write("no annotations here")
            with open(os.path.join(s_dir, "b.ann"), "w") as f:
                f.write("")

            r = run_eval(g_dir, s_dir, "strict")
            assert r["entity_metrics"]["Drug"]["fn"] == 1
            assert r["entity_metrics"]["Drug"]["tp"] == 0
            assert r["entity_metrics"]["Dosage"]["fn"] == 1
            assert r["entity_metrics"]["Dosage"]["tp"] == 0
            # Both docs appear in per_document
            assert "a" in r["per_document"]
            assert "b" in r["per_document"]
        finally:
            shutil.rmtree(g_dir, ignore_errors=True)
            shutil.rmtree(s_dir, ignore_errors=True)

    def test_system_only_doc_contributes_fp(self):
        """A document in system but not gold → all entities are FP."""
        g_dir = tempfile.mkdtemp()
        s_dir = tempfile.mkdtemp()
        try:
            with open(os.path.join(g_dir, "c.txt"), "w") as f:
                f.write("nothing")
            with open(os.path.join(g_dir, "c.ann"), "w") as f:
                f.write("")
            with open(os.path.join(s_dir, "c.txt"), "w") as f:
                f.write("nothing")
            with open(os.path.join(s_dir, "c.ann"), "w") as f:
                f.write("")
            with open(os.path.join(s_dir, "d.txt"), "w") as f:
                f.write("Metformin 500mg")
            with open(os.path.join(s_dir, "d.ann"), "w") as f:
                f.write("T1\tDrug 0 9\tMetformin\n")

            r = run_eval(g_dir, s_dir, "strict")
            assert r["entity_metrics"]["Drug"]["fp"] == 1
            assert r["entity_metrics"]["Drug"]["tp"] == 0
            assert "d" in r["per_document"]
        finally:
            shutil.rmtree(g_dir, ignore_errors=True)
            shutil.rmtree(s_dir, ignore_errors=True)

    def test_mixed_asymmetry_aggregate(self):
        """Common + gold-only + system-only docs interact in aggregate."""
        g_dir = tempfile.mkdtemp()
        s_dir = tempfile.mkdtemp()
        try:
            # Common doc: 1 Drug matched
            for d in (g_dir, s_dir):
                with open(os.path.join(d, "shared.txt"), "w") as f:
                    f.write("Aspirin daily")
                with open(os.path.join(d, "shared.ann"), "w") as f:
                    f.write("T1\tDrug 0 7\tAspirin\n")
            # Gold-only: 1 Drug → FN
            with open(os.path.join(g_dir, "gonly.txt"), "w") as f:
                f.write("Lisinopril 10mg")
            with open(os.path.join(g_dir, "gonly.ann"), "w") as f:
                f.write("T1\tDrug 0 10\tLisinopril\n")
            # System-only: 1 Drug → FP
            with open(os.path.join(s_dir, "sonly.txt"), "w") as f:
                f.write("Metoprolol 25mg")
            with open(os.path.join(s_dir, "sonly.ann"), "w") as f:
                f.write("T1\tDrug 0 9\tMetoprolol\n")

            r = run_eval(g_dir, s_dir, "strict")
            d = r["entity_metrics"]["Drug"]
            assert d["tp"] == 1
            assert d["fp"] == 1
            assert d["fn"] == 1
            # Micro: P=1/2=0.5, R=1/2=0.5, F1=0.5
            assert abs(r["micro"]["precision"] - 0.5) < 1e-6
            assert abs(r["micro"]["recall"] - 0.5) < 1e-6
            assert abs(r["micro"]["f1"] - 0.5) < 1e-6
            assert len(r["per_document"]) == 3
        finally:
            shutil.rmtree(g_dir, ignore_errors=True)
            shutil.rmtree(s_dir, ignore_errors=True)

    def test_gold_only_per_document_all_fn(self):
        """Gold-only doc: per_document entry has all entities as FN."""
        g_dir = tempfile.mkdtemp()
        s_dir = tempfile.mkdtemp()
        try:
            with open(os.path.join(g_dir, "goldonly.txt"), "w") as f:
                f.write("Warfarin 5mg twice daily")
            with open(os.path.join(g_dir, "goldonly.ann"), "w") as f:
                f.write("T1\tDrug 0 8\tWarfarin\n")
                f.write("T2\tDosage 9 12\t5mg\n")
                f.write("T3\tFrequency 13 24\ttwice daily\n")
            # Empty system dir
            with open(os.path.join(s_dir, "empty.txt"), "w") as f:
                f.write("")
            with open(os.path.join(s_dir, "empty.ann"), "w") as f:
                f.write("")

            r = run_eval(g_dir, s_dir, "strict")
            gd = r["per_document"]["goldonly"]
            assert gd["entity_metrics"]["Drug"]["fn"] == 1
            assert gd["entity_metrics"]["Drug"]["tp"] == 0
            assert gd["entity_metrics"]["Dosage"]["fn"] == 1
            assert gd["entity_metrics"]["Frequency"]["fn"] == 1
            assert abs(gd["micro"]["recall"]) < 1e-9
            assert abs(gd["micro"]["precision"]) < 1e-9
        finally:
            shutil.rmtree(g_dir, ignore_errors=True)
            shutil.rmtree(s_dir, ignore_errors=True)

    def test_system_only_relations_are_fp(self):
        """System-only doc: relations count as FP."""
        g_dir = tempfile.mkdtemp()
        s_dir = tempfile.mkdtemp()
        try:
            with open(os.path.join(g_dir, "x.txt"), "w") as f:
                f.write("")
            with open(os.path.join(g_dir, "x.ann"), "w") as f:
                f.write("")
            with open(os.path.join(s_dir, "x.txt"), "w") as f:
                f.write("")
            with open(os.path.join(s_dir, "x.ann"), "w") as f:
                f.write("")
            with open(os.path.join(s_dir, "y.txt"), "w") as f:
                f.write("Aspirin 81mg for pain")
            with open(os.path.join(s_dir, "y.ann"), "w") as f:
                f.write("T1\tDrug 0 7\tAspirin\n")
                f.write("T2\tDosage 8 12\t81mg\n")
                f.write("R1\tDosage-Drug Arg1:T2 Arg2:T1\n")

            r = run_eval(g_dir, s_dir, "strict")
            assert r["entity_metrics"]["Drug"]["fp"] == 1
            assert r["entity_metrics"]["Dosage"]["fp"] == 1
            assert r["relation_metrics"]["Dosage-Drug"]["fp"] == 1
            assert r["relation_metrics"]["Dosage-Drug"]["tp"] == 0
        finally:
            shutil.rmtree(g_dir, ignore_errors=True)
            shutil.rmtree(s_dir, ignore_errors=True)

    def test_gold_only_relations_are_fn(self):
        """Gold-only doc: relations count as FN."""
        g_dir = tempfile.mkdtemp()
        s_dir = tempfile.mkdtemp()
        try:
            with open(os.path.join(g_dir, "z.txt"), "w") as f:
                f.write("Aspirin 81mg for pain")
            with open(os.path.join(g_dir, "z.ann"), "w") as f:
                f.write("T1\tDrug 0 7\tAspirin\n")
                f.write("T2\tDosage 8 12\t81mg\n")
                f.write("R1\tDosage-Drug Arg1:T2 Arg2:T1\n")
            with open(os.path.join(s_dir, "w.txt"), "w") as f:
                f.write("")
            with open(os.path.join(s_dir, "w.ann"), "w") as f:
                f.write("")

            r = run_eval(g_dir, s_dir, "strict")
            assert r["entity_metrics"]["Drug"]["fn"] == 1
            assert r["entity_metrics"]["Dosage"]["fn"] == 1
            assert r["relation_metrics"]["Dosage-Drug"]["fn"] == 1
            assert r["relation_metrics"]["Dosage-Drug"]["tp"] == 0
        finally:
            shutil.rmtree(g_dir, ignore_errors=True)
            shutil.rmtree(s_dir, ignore_errors=True)
