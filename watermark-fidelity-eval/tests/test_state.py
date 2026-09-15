"""Tests for text watermarking pipeline.

"""
import json
import os
import subprocess
import tempfile
import pytest

CORPUS = "/app/data/corpus.jsonl"
SYNONYMS = "/app/data/synonyms.json"
ATTACK_SCRIPT = "/app/attacks/attack.py"
WATERMARK_SCRIPT = "/app/watermark.py"
EVALUATE_SCRIPT = "/app/evaluate.py"
KEY = "test-secret-key-12345"


def load_jsonl(path):
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def run_cmd(cmd, timeout=120):
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {cmd}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


@pytest.fixture(scope="session")
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture(scope="session")
def watermarked_file(tmp_dir):
    output = os.path.join(tmp_dir, "watermarked.jsonl")
    run_cmd(
        f'python3 {WATERMARK_SCRIPT} embed --key "{KEY}" '
        f"--input {CORPUS} --output {output}"
    )
    return output


@pytest.fixture(scope="session")
def split_corpus():
    entries = load_jsonl(CORPUS)
    half = len(entries) // 2
    return entries[:half], entries[half:]


class TestEmbedder:
    def test_output_format(self, watermarked_file):
        """Embedder produces valid JSONL with id and text fields."""
        entries = load_jsonl(watermarked_file)
        assert len(entries) > 0, "Embedder produced empty output"
        for entry in entries:
            assert "id" in entry, "Missing 'id' field in embedder output"
            assert "text" in entry, "Missing 'text' field in embedder output"
            assert isinstance(entry["text"], str)
            assert len(entry["text"]) > 0, f"Empty text for doc {entry['id']}"

    def test_preserves_ids(self, watermarked_file):
        """Output IDs match input IDs in order."""
        original = load_jsonl(CORPUS)
        watermarked = load_jsonl(watermarked_file)
        assert len(original) == len(watermarked), "Document count mismatch"
        orig_ids = [e["id"] for e in original]
        wm_ids = [e["id"] for e in watermarked]
        assert orig_ids == wm_ids, "Document IDs do not match or are out of order"

    def test_text_fidelity(self, watermarked_file):
        """Word overlap between original and watermarked text >= 0.70."""
        original = load_jsonl(CORPUS)
        watermarked = load_jsonl(watermarked_file)
        orig_map = {e["id"]: e["text"] for e in original}
        wm_map = {e["id"]: e["text"] for e in watermarked}
        total_overlap = 0
        count = 0
        for doc_id, orig_text in orig_map.items():
            wm_text = wm_map.get(doc_id, "")
            orig_words = set(orig_text.lower().split())
            wm_words = set(wm_text.lower().split())
            if len(orig_words) == 0:
                continue
            overlap = len(orig_words & wm_words) / max(len(orig_words), len(wm_words))
            total_overlap += overlap
            count += 1
        avg_overlap = total_overlap / count if count > 0 else 0
        assert avg_overlap >= 0.70, f"Word overlap too low: {avg_overlap:.3f}"


class TestDetector:
    def test_clean_detection(self, tmp_dir, split_corpus):
        """Detector correctly classifies watermarked vs non-watermarked on clean text."""
        set_a, set_b = split_corpus

        set_a_file = os.path.join(tmp_dir, "det_set_a.jsonl")
        wm_a_file = os.path.join(tmp_dir, "det_wm_a.jsonl")
        with open(set_a_file, "w") as f:
            for e in set_a:
                f.write(json.dumps(e) + "\n")

        run_cmd(
            f'python3 {WATERMARK_SCRIPT} embed --key "{KEY}" '
            f"--input {set_a_file} --output {wm_a_file}"
        )

        mixed_file = os.path.join(tmp_dir, "det_mixed_clean.jsonl")
        truth_file = os.path.join(tmp_dir, "det_truth_clean.jsonl")
        wm_a = load_jsonl(wm_a_file)

        with open(mixed_file, "w") as fm, open(truth_file, "w") as ft:
            for e in wm_a:
                fm.write(json.dumps(e) + "\n")
                ft.write(json.dumps({"id": e["id"], "label": 1.0}) + "\n")
            for e in set_b:
                fm.write(json.dumps(e) + "\n")
                ft.write(json.dumps({"id": e["id"], "label": 0.0}) + "\n")

        det_file = os.path.join(tmp_dir, "det_clean_out.jsonl")
        run_cmd(
            f'python3 {WATERMARK_SCRIPT} detect --key "{KEY}" '
            f"--input {mixed_file} --output {det_file}"
        )

        detections = {e["id"]: e["label"] for e in load_jsonl(det_file)}
        truths = {e["id"]: e["label"] for e in load_jsonl(truth_file)}

        tp = sum(
            1 for did in truths if truths[did] >= 0.5 and detections.get(did, 0) >= 0.5
        )
        fn = sum(
            1 for did in truths if truths[did] >= 0.5 and detections.get(did, 0) < 0.5
        )
        tn = sum(
            1 for did in truths if truths[did] < 0.5 and detections.get(did, 0) < 0.5
        )
        fp = sum(
            1 for did in truths if truths[did] < 0.5 and detections.get(did, 0) >= 0.5
        )

        tpr = tp / (tp + fn) if (tp + fn) > 0 else 0
        tnr = tn / (tn + fp) if (tn + fp) > 0 else 0
        balanced_acc = (tpr + tnr) / 2

        assert balanced_acc >= 0.90, (
            f"Clean balanced accuracy too low: {balanced_acc:.3f} "
            f"(TP={tp}, FN={fn}, TN={tn}, FP={fp})"
        )

    def test_post_attack_detection(self, tmp_dir, split_corpus):
        """Detector maintains accuracy after mixed attack."""
        set_a, set_b = split_corpus

        set_a_file = os.path.join(tmp_dir, "atk_set_a.jsonl")
        wm_a_file = os.path.join(tmp_dir, "atk_wm_a.jsonl")
        with open(set_a_file, "w") as f:
            for e in set_a:
                f.write(json.dumps(e) + "\n")

        run_cmd(
            f'python3 {WATERMARK_SCRIPT} embed --key "{KEY}" '
            f"--input {set_a_file} --output {wm_a_file}"
        )

        attack_dir = os.path.join(tmp_dir, "atk_attacked")
        run_cmd(f"python3 {ATTACK_SCRIPT} mixed {wm_a_file} {attack_dir}")
        attacked_file = os.path.join(attack_dir, "texts.jsonl")

        mixed_file = os.path.join(tmp_dir, "atk_mixed.jsonl")
        truth_file = os.path.join(tmp_dir, "atk_truth.jsonl")
        attacked_a = load_jsonl(attacked_file)

        with open(mixed_file, "w") as fm, open(truth_file, "w") as ft:
            for e in attacked_a:
                fm.write(json.dumps(e) + "\n")
                ft.write(json.dumps({"id": e["id"], "label": 1.0}) + "\n")
            for e in set_b:
                fm.write(json.dumps(e) + "\n")
                ft.write(json.dumps({"id": e["id"], "label": 0.0}) + "\n")

        det_file = os.path.join(tmp_dir, "atk_det_out.jsonl")
        run_cmd(
            f'python3 {WATERMARK_SCRIPT} detect --key "{KEY}" '
            f"--input {mixed_file} --output {det_file}"
        )

        detections = {e["id"]: e["label"] for e in load_jsonl(det_file)}
        truths = {e["id"]: e["label"] for e in load_jsonl(truth_file)}

        tp = sum(
            1 for did in truths if truths[did] >= 0.5 and detections.get(did, 0) >= 0.5
        )
        fn = sum(
            1 for did in truths if truths[did] >= 0.5 and detections.get(did, 0) < 0.5
        )
        tn = sum(
            1 for did in truths if truths[did] < 0.5 and detections.get(did, 0) < 0.5
        )
        fp = sum(
            1 for did in truths if truths[did] < 0.5 and detections.get(did, 0) >= 0.5
        )

        tpr = tp / (tp + fn) if (tp + fn) > 0 else 0
        tnr = tn / (tn + fp) if (tn + fp) > 0 else 0
        balanced_acc = (tpr + tnr) / 2

        assert balanced_acc >= 0.70, (
            f"Post-attack balanced accuracy too low: {balanced_acc:.3f} "
            f"(TP={tp}, FN={fn}, TN={tn}, FP={fp})"
        )


class TestEvaluator:
    def test_output_format(self, tmp_dir, watermarked_file):
        """Evaluator produces valid JSON with all required fields."""
        det_file = os.path.join(tmp_dir, "eval_fmt_det.jsonl")
        truth_file = os.path.join(tmp_dir, "eval_fmt_truth.jsonl")

        entries = load_jsonl(watermarked_file)
        with open(det_file, "w") as fd, open(truth_file, "w") as ft:
            for e in entries:
                fd.write(json.dumps({"id": e["id"], "label": 1.0}) + "\n")
                ft.write(json.dumps({"id": e["id"], "label": 1.0}) + "\n")

        output = os.path.join(tmp_dir, "eval_fmt_output.json")
        run_cmd(
            f"python3 {EVALUATE_SCRIPT} --original {CORPUS} "
            f"--watermarked {watermarked_file} --detection {det_file} "
            f"--ground-truth {truth_file} --output {output}"
        )

        with open(output) as f:
            result = json.load(f)

        for field in ["twf", "balanced_accuracy", "bleu", "confusion"]:
            assert field in result, f"Missing field '{field}' in evaluator output"
        assert isinstance(result["confusion"], list)
        assert len(result["confusion"]) == 2
        assert len(result["confusion"][0]) == 2
        assert len(result["confusion"][1]) == 2
        assert 0.0 <= result["twf"] <= 1.0
        assert 0.0 <= result["balanced_accuracy"] <= 1.0
        assert 0.0 <= result["bleu"] <= 1.0

    def test_twf_formula(self, tmp_dir):
        """TWF equals BLEU * Balanced Accuracy."""
        orig_file = os.path.join(tmp_dir, "ctrl_orig.jsonl")
        wm_file = os.path.join(tmp_dir, "ctrl_wm.jsonl")
        det_file = os.path.join(tmp_dir, "ctrl_det.jsonl")
        truth_file = os.path.join(tmp_dir, "ctrl_truth.jsonl")

        with open(orig_file, "w") as fo, open(wm_file, "w") as fw:
            for i in range(10):
                text = f"This is a test document number {i} with some important content about policy."
                fo.write(json.dumps({"id": f"t{i}", "text": text}) + "\n")
                fw.write(json.dumps({"id": f"t{i}", "text": text}) + "\n")

        with open(det_file, "w") as fd, open(truth_file, "w") as ft:
            for i in range(10):
                fd.write(json.dumps({"id": f"t{i}", "label": 1.0}) + "\n")
                ft.write(json.dumps({"id": f"t{i}", "label": 1.0}) + "\n")

        output = os.path.join(tmp_dir, "ctrl_eval.json")
        run_cmd(
            f"python3 {EVALUATE_SCRIPT} --original {orig_file} "
            f"--watermarked {wm_file} --detection {det_file} "
            f"--ground-truth {truth_file} --output {output}"
        )

        with open(output) as f:
            result = json.load(f)

        assert result["bleu"] >= 0.95, f"BLEU on identical texts: {result['bleu']}"
        expected_twf = result["bleu"] * result["balanced_accuracy"]
        assert abs(result["twf"] - round(expected_twf, 4)) < 0.02, (
            f"TWF mismatch: got {result['twf']}, "
            f"expected bleu*ba = {result['bleu']}*{result['balanced_accuracy']} = {expected_twf:.4f}"
        )


class TestEndToEnd:
    def test_full_pipeline(self, tmp_dir, split_corpus):
        """Full embed -> attack -> detect -> evaluate pipeline achieves required metrics."""
        set_a, set_b = split_corpus

        set_a_file = os.path.join(tmp_dir, "e2e_a.jsonl")
        wm_file = os.path.join(tmp_dir, "e2e_wm.jsonl")
        with open(set_a_file, "w") as f:
            for e in set_a:
                f.write(json.dumps(e) + "\n")

        run_cmd(
            f'python3 {WATERMARK_SCRIPT} embed --key "{KEY}" '
            f"--input {set_a_file} --output {wm_file}"
        )

        attack_dir = os.path.join(tmp_dir, "e2e_attack")
        run_cmd(f"python3 {ATTACK_SCRIPT} mixed {wm_file} {attack_dir}")
        attacked_file = os.path.join(attack_dir, "texts.jsonl")

        mixed_file = os.path.join(tmp_dir, "e2e_mixed.jsonl")
        truth_file = os.path.join(tmp_dir, "e2e_truth.jsonl")
        attacked = load_jsonl(attacked_file)

        with open(mixed_file, "w") as fm, open(truth_file, "w") as ft:
            for e in attacked:
                fm.write(json.dumps(e) + "\n")
                ft.write(json.dumps({"id": e["id"], "label": 1.0}) + "\n")
            for e in set_b:
                fm.write(json.dumps(e) + "\n")
                ft.write(json.dumps({"id": e["id"], "label": 0.0}) + "\n")

        det_file = os.path.join(tmp_dir, "e2e_det.jsonl")
        run_cmd(
            f'python3 {WATERMARK_SCRIPT} detect --key "{KEY}" '
            f"--input {mixed_file} --output {det_file}"
        )

        output = os.path.join(tmp_dir, "e2e_eval.json")
        run_cmd(
            f"python3 {EVALUATE_SCRIPT} --original {set_a_file} "
            f"--watermarked {wm_file} --detection {det_file} "
            f"--ground-truth {truth_file} --output {output}"
        )

        with open(output) as f:
            result = json.load(f)

        assert result["twf"] >= 0.45, f"TWF too low: {result['twf']}"
        assert result["bleu"] >= 0.65, f"BLEU too low: {result['bleu']}"
        assert result["balanced_accuracy"] >= 0.65, (
            f"Balanced accuracy too low: {result['balanced_accuracy']}"
        )

    def test_different_keys(self, tmp_dir):
        """Different keys produce different detection: correct key detects, wrong key does not."""
        test_file = os.path.join(tmp_dir, "key_test.jsonl")
        entries = load_jsonl(CORPUS)[:8]
        with open(test_file, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        key1 = "secret-key-alpha-9876"
        key2 = "secret-key-beta-5432"

        wm_file = os.path.join(tmp_dir, "key_wm.jsonl")
        run_cmd(
            f'python3 {WATERMARK_SCRIPT} embed --key "{key1}" '
            f"--input {test_file} --output {wm_file}"
        )

        det1_file = os.path.join(tmp_dir, "key_det1.jsonl")
        run_cmd(
            f'python3 {WATERMARK_SCRIPT} detect --key "{key1}" '
            f"--input {wm_file} --output {det1_file}"
        )

        det2_file = os.path.join(tmp_dir, "key_det2.jsonl")
        run_cmd(
            f'python3 {WATERMARK_SCRIPT} detect --key "{key2}" '
            f"--input {wm_file} --output {det2_file}"
        )

        det1 = load_jsonl(det1_file)
        det2 = load_jsonl(det2_file)

        correct_detections = sum(1 for e in det1 if e["label"] >= 0.5)
        assert correct_detections >= len(det1) * 0.75, (
            f"Correct key detection rate too low: {correct_detections}/{len(det1)}"
        )

        wrong_detections = sum(1 for e in det2 if e["label"] >= 0.5)
        assert wrong_detections <= len(det2) * 0.50, (
            f"Wrong key false positive rate too high: {wrong_detections}/{len(det2)}"
        )
