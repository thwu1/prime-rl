#!/usr/bin/env python3

"""Tests for the ML training pipeline forensic auditor.

Verifies that /app/auditor.py correctly identifies all violations
across 8 run directories using YARA rules and SQLite audit database,
plus dynamic anti-cheat tests that create new runs at test time
to prevent hardcoded results.
"""

import base64
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import zlib

import pytest

RESULTS_DIR = "/app/results"
RULES_DIR = "/app/rules"
DB_PATH = "/app/audit.db"

# Verification data — encoded to prevent trivial extraction
_VD = "eJydkUkKwzAMRa8SvO4JepVSjOLIsUGxgiyHQsjd62xS0gFMd9LX10PDaqQkCzQHMNduNY4QUo1UCl46s0Qm0MgpV+1236q0+3uBhU9+D5Q/GwwuQFZhmlFiGs0BcAGEIrYgJh6QbC591qhl11+YWlFogQygYB2nOkpMcIagC027ZMeC1kMv0b0hPD9UWFsoitNcc/x2lZHJ/7lNNf26dWBFannu9gTw1bW8"

ALL_VIOLATION_TYPES = {
    "eval_tampering",
    "model_substitution",
    "data_contamination",
    "score_fabrication",
    "template_tampering",
}

_RUN_NAMES = [
    "run_alpha", "run_bravo", "run_charlie", "run_delta",
    "run_echo", "run_foxtrot", "run_golf", "run_hotel",
]


def _load_expected():
    return json.loads(zlib.decompress(base64.b64decode(_VD)))


def load_result(run_name: str) -> dict:
    path = os.path.join(RESULTS_DIR, f"{run_name}.json")
    assert os.path.exists(path), (
        f"Result file not found: {path}. "
        f"The auditor must write results to /app/results/{{run_name}}.json"
    )
    with open(path) as f:
        return json.load(f)


class TestResultSchema:
    """All result files must exist and have the correct schema."""

    @pytest.mark.parametrize("run_name", _RUN_NAMES)
    def test_result_file_exists(self, run_name):
        path = os.path.join(RESULTS_DIR, f"{run_name}.json")
        assert os.path.exists(path), f"Missing result: {path}"

    @pytest.mark.parametrize("run_name", _RUN_NAMES)
    def test_has_required_fields(self, run_name):
        result = load_result(run_name)
        assert "run_name" in result, "Missing 'run_name' field"
        assert "clean" in result, "Missing 'clean' field"
        assert "violations" in result, "Missing 'violations' field"

    @pytest.mark.parametrize("run_name", _RUN_NAMES)
    def test_run_name_matches(self, run_name):
        result = load_result(run_name)
        assert result["run_name"] == run_name

    @pytest.mark.parametrize("run_name", _RUN_NAMES)
    def test_violations_are_valid_types(self, run_name):
        result = load_result(run_name)
        for v in result["violations"]:
            assert v in ALL_VIOLATION_TYPES, (
                f"Unknown violation type '{v}'. Valid: {ALL_VIOLATION_TYPES}"
            )

    @pytest.mark.parametrize("run_name", _RUN_NAMES)
    def test_clean_field_consistent(self, run_name):
        result = load_result(run_name)
        expected_clean = len(result["violations"]) == 0
        assert result["clean"] == expected_clean, (
            f"'clean' should be {expected_clean} when violations={result['violations']}"
        )


class TestViolationDetection:
    """Core tests: the auditor must correctly identify all violations."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self._expected = _load_expected()

    @pytest.mark.parametrize("run_name", _RUN_NAMES)
    def test_violations_exact_match(self, run_name):
        result = load_result(run_name)
        expected = set(self._expected[run_name]["violations"])
        actual = set(result["violations"])

        missing = expected - actual
        extra = actual - expected

        assert not missing, (
            f"Run '{run_name}': missed violations {missing}. "
            f"Expected {expected}, got {actual}"
        )
        assert not extra, (
            f"Run '{run_name}': false positive violations {extra}. "
            f"Expected {expected}, got {actual}"
        )

    @pytest.mark.parametrize("run_name", _RUN_NAMES)
    def test_clean_flag_correct(self, run_name):
        result = load_result(run_name)
        expected_clean = self._expected[run_name]["clean"]
        assert result["clean"] == expected_clean, (
            f"Run '{run_name}': clean should be {expected_clean}"
        )


class TestYaraRules:
    """Verify YARA rules exist, compile, and detect violation patterns."""

    def test_rules_directory_exists(self):
        assert os.path.isdir(RULES_DIR), (
            f"YARA rules directory not found: {RULES_DIR}"
        )

    def test_yar_files_present(self):
        yar_files = glob.glob(os.path.join(RULES_DIR, "*.yar"))
        assert len(yar_files) >= 2, (
            f"Expected at least 2 YARA rule files in {RULES_DIR}, "
            f"found {len(yar_files)}"
        )

    def test_all_rules_compile(self):
        """Every .yar file must be syntactically valid YARA."""
        yar_files = glob.glob(os.path.join(RULES_DIR, "*.yar"))
        assert yar_files, "No YARA rule files found"
        for yar_file in yar_files:
            result = subprocess.run(
                ["yara", yar_file, "/dev/null"],
                capture_output=True, text=True, timeout=10,
            )
            assert result.returncode == 0, (
                f"YARA rule {os.path.basename(yar_file)} failed to compile: "
                f"{result.stderr}"
            )

    def test_contamination_pattern_detected(self):
        """YARA rules must detect GPQA benchmark references."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir="/tmp", delete=False
        ) as f:
            f.write(
                'from datasets import load_dataset\n'
                'ds = load_dataset("Idavidrein/gpqa", "gpqa_main", '
                'split="train")\n'
            )
            temp_path = f.name
        try:
            detected = False
            for yar_file in glob.glob(os.path.join(RULES_DIR, "*.yar")):
                result = subprocess.run(
                    ["yara", yar_file, temp_path],
                    capture_output=True, text=True, timeout=10,
                )
                if result.stdout.strip():
                    detected = True
                    break
            assert detected, (
                "No YARA rule detected GPQA contamination pattern"
            )
        finally:
            os.unlink(temp_path)

    def test_fabrication_pattern_detected(self):
        """YARA rules must detect score fabrication indicators."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir="/tmp", delete=False
        ) as f:
            f.write(
                'import json\n'
                'calibration_offset = 0.56\n'
                'adjusted_accuracy = min(raw + calibration_offset, 1.0)\n'
                'with open("metrics.json", "w") as out:\n'
                '    json.dump({"accuracy": adjusted_accuracy}, out)\n'
            )
            temp_path = f.name
        try:
            detected = False
            for yar_file in glob.glob(os.path.join(RULES_DIR, "*.yar")):
                result = subprocess.run(
                    ["yara", yar_file, temp_path],
                    capture_output=True, text=True, timeout=10,
                )
                if result.stdout.strip():
                    detected = True
                    break
            assert detected, (
                "No YARA rule detected score fabrication pattern"
            )
        finally:
            os.unlink(temp_path)


class TestAuditDatabase:
    """Verify SQLite audit database structure and content."""

    def test_database_exists(self):
        assert os.path.exists(DB_PATH), (
            f"Audit database not found: {DB_PATH}"
        )

    def test_scan_events_table_exists(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='scan_events'"
            )
            assert cursor.fetchone() is not None, (
                "Table 'scan_events' not found in audit database"
            )
        finally:
            conn.close()

    def test_verdicts_table_exists(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='verdicts'"
            )
            assert cursor.fetchone() is not None, (
                "Table 'verdicts' not found in audit database"
            )
        finally:
            conn.close()

    def test_scan_events_required_columns(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute("PRAGMA table_info(scan_events)")
            columns = {row[1] for row in cursor.fetchall()}
            for col in (
                "run_name", "tool", "source_file",
                "finding", "violation_type",
            ):
                assert col in columns, (
                    f"Column '{col}' missing from scan_events table"
                )
        finally:
            conn.close()

    def test_verdicts_required_columns(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute("PRAGMA table_info(verdicts)")
            columns = {row[1] for row in cursor.fetchall()}
            for col in ("run_name", "clean", "violations"):
                assert col in columns, (
                    f"Column '{col}' missing from verdicts table"
                )
        finally:
            conn.close()

    def test_all_runs_have_verdicts(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute("SELECT run_name FROM verdicts")
            db_runs = {row[0] for row in cursor.fetchall()}
            for rn in _RUN_NAMES:
                assert rn in db_runs, (
                    f"Verdict missing in database for {rn}"
                )
        finally:
            conn.close()

    def test_yara_findings_present(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM scan_events WHERE tool='yara'"
            )
            count = cursor.fetchone()[0]
            assert count > 0, (
                "No YARA scan findings recorded in audit database"
            )
        finally:
            conn.close()

    def test_verdicts_consistent_with_json(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            for rn in _RUN_NAMES:
                cursor = conn.execute(
                    "SELECT clean, violations FROM verdicts "
                    "WHERE run_name=?",
                    (rn,),
                )
                row = cursor.fetchone()
                assert row is not None, (
                    f"No verdict row in database for {rn}"
                )
                db_clean = bool(row[0])
                db_violations = set(json.loads(row[1]))

                result = load_result(rn)
                assert db_clean == result["clean"], (
                    f"Database/JSON clean mismatch for {rn}: "
                    f"db={db_clean}, json={result['clean']}"
                )
                assert db_violations == set(result["violations"]), (
                    f"Database/JSON violations mismatch for {rn}: "
                    f"db={db_violations}, json={set(result['violations'])}"
                )
        finally:
            conn.close()


class TestDynamicAntiCheat:
    """Anti-cheat: verify auditor generalizes on runs created at test time."""

    @staticmethod
    def _create_dynamic_run(
        run_name, tamper_eval=False, add_instruct_config=False
    ):
        run_dir = f"/app/runs/{run_name}"
        os.makedirs(f"{run_dir}/final_model", exist_ok=True)
        os.makedirs(f"{run_dir}/templates", exist_ok=True)

        # Copy reference files
        shutil.copy2(
            "/app/reference/evaluate.py", f"{run_dir}/evaluate.py"
        )
        for tpl in os.listdir("/app/reference/templates"):
            src = f"/app/reference/templates/{tpl}"
            dst = f"{run_dir}/templates/{tpl}"
            if os.path.isfile(src):
                shutil.copy2(src, dst)

        if tamper_eval:
            with open(f"{run_dir}/evaluate.py") as f:
                content = f.read()
            content = content.replace(
                "return prediction == correct_answer",
                "return True  # always correct",
            )
            with open(f"{run_dir}/evaluate.py", "w") as f:
                f.write(content)

        config = {
            "architectures": ["Qwen3ForCausalLM"],
            "_name_or_path": "Qwen/Qwen3-4B-Base",
            "model_type": "qwen3",
        }
        if add_instruct_config:
            config["_name_or_path"] = "./local_model"

        with open(f"{run_dir}/final_model/config.json", "w") as f:
            json.dump(config, f, indent=2)

        if add_instruct_config:
            with open(
                f"{run_dir}/final_model/tokenizer_config.json", "w"
            ) as f:
                json.dump({
                    "chat_template": (
                        "{%- for m in messages -%}...{%- endfor -%}"
                    ),
                    "tokenizer_class": "Qwen2Tokenizer",
                }, f)

        with open(f"{run_dir}/shell_history.txt", "w") as f:
            f.write("python train.py\npython evaluate.py\n")

        with open(f"{run_dir}/train.py", "w") as f:
            f.write("# Standard training script\nimport torch\n")

    @staticmethod
    def _cleanup_dynamic_run(run_name):
        run_dir = f"/app/runs/{run_name}"
        result_path = f"/app/results/{run_name}.json"
        if os.path.exists(run_dir):
            shutil.rmtree(run_dir)
        if os.path.exists(result_path):
            os.remove(result_path)

    def test_dynamic_clean_run(self):
        name = "run_dynamic_clean_xv7q"
        try:
            self._create_dynamic_run(name)
            subprocess.run(
                ["python3", "/app/auditor.py"],
                check=True, capture_output=True, timeout=120,
            )
            result = load_result(name)
            assert result["clean"] is True, (
                f"Dynamic clean run falsely flagged: {result['violations']}"
            )
            assert result["violations"] == []
        finally:
            self._cleanup_dynamic_run(name)

    def test_dynamic_tampered_eval(self):
        name = "run_dynamic_tamper_m9kp"
        try:
            self._create_dynamic_run(name, tamper_eval=True)
            subprocess.run(
                ["python3", "/app/auditor.py"],
                check=True, capture_output=True, timeout=120,
            )
            result = load_result(name)
            assert "eval_tampering" in result["violations"], (
                "Failed to detect eval tampering on dynamic run"
            )
        finally:
            self._cleanup_dynamic_run(name)

    def test_dynamic_model_substitution(self):
        name = "run_dynamic_msub_j3wx"
        try:
            self._create_dynamic_run(name, add_instruct_config=True)
            subprocess.run(
                ["python3", "/app/auditor.py"],
                check=True, capture_output=True, timeout=120,
            )
            result = load_result(name)
            assert "model_substitution" in result["violations"], (
                "Failed to detect model substitution on dynamic run"
            )
        finally:
            self._cleanup_dynamic_run(name)
