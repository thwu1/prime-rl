
import subprocess
import json
import os
import math
import tempfile

import yaml


def run_cmd(cmd, timeout=60):
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    return result


# ---------------------------------------------------------------------------
# Validation tests: check exact violation sets for each broken config
# ---------------------------------------------------------------------------

class TestValidateBroken:

    def test_validate_broken_1(self):
        """300B FP8 SFT, 16 GPUs: TP not power of 2, bad pp_seg, missing hadamard, AMP overlap"""
        r = run_cmd(
            "python3 /app/validator.py validate /app/configs/broken_1.yaml "
            "--model ERNIE-4.5-300B-A47B --num-gpus 16"
        )
        assert r.returncode == 0, f"validator failed: {r.stderr}"
        out = json.loads(r.stdout)
        rules = {v["rule"] for v in out["violations"]}
        expected = {
            "TP_POWER_OF_TWO", "PP_SEG_METHOD", "FP8_HADAMARD",
            "AMP_DISJOINT", "PARALLEL_PRODUCT"
        }
        assert rules == expected, f"Expected {expected}, got {rules}"
        assert out["num_violations"] == 5

    def test_validate_broken_2(self):
        """21B SFT, 8 GPUs: bad sharding, bad lr, missing moe_group, bad fp16_opt"""
        r = run_cmd(
            "python3 /app/validator.py validate /app/configs/broken_2.yaml "
            "--model ERNIE-4.5-21B-A3B --num-gpus 8"
        )
        assert r.returncode == 0, f"validator failed: {r.stderr}"
        out = json.loads(r.stdout)
        rules = {v["rule"] for v in out["violations"]}
        expected = {"SHARDING_VALID", "LR_SCHEDULER", "MOE_GROUP", "FP16_OPT_LEVEL"}
        assert rules == expected, f"Expected {expected}, got {rules}"
        assert out["num_violations"] == 4

    def test_validate_broken_3(self):
        """0.3B FP8, 1 GPU: bad batch, bad optim, hadamard False, missing fp8 optim flags"""
        r = run_cmd(
            "python3 /app/validator.py validate /app/configs/broken_3.yaml "
            "--model ERNIE-4.5-0.3B --num-gpus 1"
        )
        assert r.returncode == 0, f"validator failed: {r.stderr}"
        out = json.loads(r.stdout)
        rules = {v["rule"] for v in out["violations"]}
        expected = {"BATCH_POSITIVE", "OPTIMIZER_VALID", "FP8_HADAMARD", "FP8_OPTIM"}
        assert rules == expected, f"Expected {expected}, got {rules}"
        assert out["num_violations"] == 4

    def test_validate_broken_4(self):
        """300B DPO, 16 GPUs: parallel product overflow, missing moe, bad pp_seg, AMP overlap"""
        r = run_cmd(
            "python3 /app/validator.py validate /app/configs/broken_4.yaml "
            "--model ERNIE-4.5-300B-A47B --num-gpus 16"
        )
        assert r.returncode == 0, f"validator failed: {r.stderr}"
        out = json.loads(r.stdout)
        rules = {v["rule"] for v in out["violations"]}
        expected = {"PARALLEL_PRODUCT", "MOE_GROUP", "PP_SEG_METHOD", "AMP_DISJOINT"}
        assert rules == expected, f"Expected {expected}, got {rules}"
        assert out["num_violations"] == 4

    def test_validate_broken_5(self):
        """21B DPO-LoRA, 1 GPU: bad TP, PP=0, bad grad_accum, bad sharding case, missing moe"""
        r = run_cmd(
            "python3 /app/validator.py validate /app/configs/broken_5.yaml "
            "--model ERNIE-4.5-21B-A3B --num-gpus 1"
        )
        assert r.returncode == 0, f"validator failed: {r.stderr}"
        out = json.loads(r.stdout)
        rules = {v["rule"] for v in out["violations"]}
        expected = {
            "TP_POWER_OF_TWO", "PP_POSITIVE", "BATCH_POSITIVE",
            "SHARDING_VALID", "MOE_GROUP", "PARALLEL_PRODUCT"
        }
        assert rules == expected, f"Expected {expected}, got {rules}"
        assert out["num_violations"] == 6

    def test_validate_reference_300b_clean(self):
        """Reference 300B config should have 0 violations"""
        r = run_cmd(
            "python3 /app/validator.py validate /app/configs/reference_300b_fp8.yaml "
            "--model ERNIE-4.5-300B-A47B --num-gpus 16"
        )
        assert r.returncode == 0, f"validator failed: {r.stderr}"
        out = json.loads(r.stdout)
        assert out["num_violations"] == 0, f"Expected 0 violations, got {out['violations']}"

    def test_validate_reference_03b_clean(self):
        """Reference 0.3B config should have 0 violations"""
        r = run_cmd(
            "python3 /app/validator.py validate /app/configs/reference_03b_bf16.yaml "
            "--model ERNIE-4.5-0.3B --num-gpus 1"
        )
        assert r.returncode == 0, f"validator failed: {r.stderr}"
        out = json.loads(r.stdout)
        assert out["num_violations"] == 0, f"Expected 0 violations, got {out['violations']}"


# ---------------------------------------------------------------------------
# Fix tests: fixed configs must pass validation
# ---------------------------------------------------------------------------

class TestFixBroken:

    def _fix_and_validate(self, broken_path, model, num_gpus):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            fixed_path = f.name
        try:
            r = run_cmd(
                f"python3 /app/validator.py fix {broken_path} "
                f"--model {model} --num-gpus {num_gpus} --output {fixed_path}"
            )
            assert r.returncode == 0, f"fix failed: {r.stderr}"
            assert os.path.exists(fixed_path), "Fixed file not written"

            r2 = run_cmd(
                f"python3 /app/validator.py validate {fixed_path} "
                f"--model {model} --num-gpus {num_gpus}"
            )
            assert r2.returncode == 0, f"validate of fixed config failed: {r2.stderr}"
            out = json.loads(r2.stdout)
            assert out["num_violations"] == 0, (
                f"Fixed config still has violations: {out['violations']}"
            )

            with open(fixed_path) as fh:
                cfg = yaml.safe_load(fh)
            return cfg
        finally:
            if os.path.exists(fixed_path):
                os.unlink(fixed_path)

    def test_fix_broken_1(self):
        cfg = self._fix_and_validate(
            "/app/configs/broken_1.yaml", "ERNIE-4.5-300B-A47B", 16
        )
        # TP should now be a power of 2
        tp = cfg.get("tensor_parallel_degree", 1)
        assert tp & (tp - 1) == 0 and tp > 0, f"TP={tp} not power of 2"
        # apply_hadamard must be True for fp8
        assert cfg.get("apply_hadamard") is True

    def test_fix_broken_2(self):
        cfg = self._fix_and_validate(
            "/app/configs/broken_2.yaml", "ERNIE-4.5-21B-A3B", 8
        )
        assert cfg.get("sharding") in ("stage1", "stage2", "stage3")
        assert cfg.get("moe_group") is not None and cfg.get("moe_group") != ""

    def test_fix_broken_3(self):
        cfg = self._fix_and_validate(
            "/app/configs/broken_3.yaml", "ERNIE-4.5-0.3B", 1
        )
        assert cfg.get("batch_size", 0) > 0
        assert cfg.get("apply_hadamard") is True

    def test_fix_broken_4(self):
        cfg = self._fix_and_validate(
            "/app/configs/broken_4.yaml", "ERNIE-4.5-300B-A47B", 16
        )
        tp = cfg.get("tensor_parallel_degree", 1)
        pp = cfg.get("pipeline_parallel_degree", 1)
        sp = cfg.get("sharding_parallel_degree", 1)
        assert tp * pp * sp <= 16
        assert 16 % (tp * pp * sp) == 0

    def test_fix_broken_5(self):
        cfg = self._fix_and_validate(
            "/app/configs/broken_5.yaml", "ERNIE-4.5-21B-A3B", 1
        )
        tp = cfg.get("tensor_parallel_degree", 1)
        pp = cfg.get("pipeline_parallel_degree", 1)
        sp = cfg.get("sharding_parallel_degree", 1)
        assert tp * pp * sp <= 1
        assert cfg.get("gradient_accumulation_steps", 0) > 0


# ---------------------------------------------------------------------------
# Memory estimation tests
# ---------------------------------------------------------------------------

class TestMemoryEstimation:

    def test_estimate_300b_fp8(self):
        """Memory estimate for reference 300B FP8 config on TP=8, PP=2"""
        r = run_cmd(
            "python3 /app/planner.py estimate /app/configs/reference_300b_fp8.yaml "
            "--model ERNIE-4.5-300B-A47B"
        )
        assert r.returncode == 0, f"estimate failed: {r.stderr}"
        out = json.loads(r.stdout)

        # Expected values computed from the formula:
        # params_per_gpu = 300e9 / (8*2) = 18.75e9
        # P = 18.75 (fp8, 1 byte), G = 37.5, O = 0 (offloaded)
        # A = 8192*1*6144*24 / 8 * 2 / 1e9 = 0.301989888
        # Total = 56.551989888
        assert abs(out["param_memory_gb"] - 18.75) < 0.01, (
            f"param_memory_gb={out['param_memory_gb']}, expected ~18.75"
        )
        assert abs(out["grad_memory_gb"] - 37.5) < 0.01
        assert abs(out["optim_memory_gb"] - 0.0) < 0.01
        assert abs(out["activation_memory_gb"] - 0.302) < 0.01
        assert abs(out["total_memory_gb"] - 56.552) < 0.01

    def test_estimate_03b_bf16(self):
        """Memory estimate for reference 0.3B BF16 config on TP=1, PP=1"""
        r = run_cmd(
            "python3 /app/planner.py estimate /app/configs/reference_03b_bf16.yaml "
            "--model ERNIE-4.5-0.3B"
        )
        assert r.returncode == 0, f"estimate failed: {r.stderr}"
        out = json.loads(r.stdout)

        # params_per_gpu = 0.3e9
        # P = 0.6, G = 0.6, O = 3.6 (no offload, 12 bytes/param)
        # A = 8192*1*1024*24 * 2 / 1e9 = 0.402653184
        # Total = 5.202653184
        assert abs(out["param_memory_gb"] - 0.6) < 0.01
        assert abs(out["grad_memory_gb"] - 0.6) < 0.01
        assert abs(out["optim_memory_gb"] - 3.6) < 0.01
        assert abs(out["activation_memory_gb"] - 0.403) < 0.01
        assert abs(out["total_memory_gb"] - 5.203) < 0.01


# ---------------------------------------------------------------------------
# Planner tests
# ---------------------------------------------------------------------------

class TestPlanner:

    def _run_plan(self, model, num_gpus, gpu_mem, seq_len, batch_size, compute_type):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            out_path = f.name
        try:
            r = run_cmd(
                f"python3 /app/planner.py plan "
                f"--model {model} --num-gpus {num_gpus} --gpu-mem-gb {gpu_mem} "
                f"--seq-len {seq_len} --batch-size {batch_size} "
                f"--compute-type {compute_type} --output {out_path}"
            )
            assert r.returncode == 0, f"planner failed: {r.stderr}"
            with open(out_path) as fh:
                cfg = yaml.safe_load(fh)
            return cfg, out_path
        except Exception:
            if os.path.exists(out_path):
                os.unlink(out_path)
            raise

    def test_plan_300b_fp8_16gpu(self):
        """300B on 16 GPUs, FP8: should select TP=4, PP=4, s=1 (cost=21)"""
        cfg, path = self._run_plan(
            "ERNIE-4.5-300B-A47B", 16, 80, 8192, 1, "fp8"
        )
        try:
            assert cfg["tensor_parallel_degree"] == 4, (
                f"Expected TP=4, got {cfg['tensor_parallel_degree']}"
            )
            assert cfg["pipeline_parallel_degree"] == 4, (
                f"Expected PP=4, got {cfg['pipeline_parallel_degree']}"
            )
            assert cfg["sharding_parallel_degree"] == 1
            assert cfg["compute_type"] == "fp8"
            assert cfg.get("apply_hadamard") is True
            assert cfg.get("moe_group") is not None
            # pp_seg_method should be [0, 15, 30, 45, 60]
            seg = cfg.get("pp_seg_method")
            assert seg is not None
            assert len(seg) == 5
            assert seg[0] == 0
            assert seg[-1] == 60
        finally:
            os.unlink(path)

    def test_plan_03b_bf16_1gpu(self):
        """0.3B on 1 GPU, BF16: should select TP=1, PP=1, s=1"""
        cfg, path = self._run_plan(
            "ERNIE-4.5-0.3B", 1, 80, 8192, 1, "bf16"
        )
        try:
            assert cfg["tensor_parallel_degree"] == 1
            assert cfg["pipeline_parallel_degree"] == 1
            assert cfg["sharding_parallel_degree"] == 1
            assert cfg["compute_type"] == "bf16"
            # No moe_group needed for dense model
            # No pp_seg_method needed for PP=1
        finally:
            os.unlink(path)

    def test_plan_21b_bf16_8gpu(self):
        """21B on 8 GPUs, BF16: should select TP=1, PP=2, s=4 (cost=11)"""
        cfg, path = self._run_plan(
            "ERNIE-4.5-21B-A3B", 8, 80, 8192, 1, "bf16"
        )
        try:
            assert cfg["tensor_parallel_degree"] == 1, (
                f"Expected TP=1, got {cfg['tensor_parallel_degree']}"
            )
            assert cfg["pipeline_parallel_degree"] == 2, (
                f"Expected PP=2, got {cfg['pipeline_parallel_degree']}"
            )
            assert cfg["sharding_parallel_degree"] == 4, (
                f"Expected s=4, got {cfg['sharding_parallel_degree']}"
            )
            assert cfg.get("moe_group") is not None
            seg = cfg.get("pp_seg_method")
            assert seg is not None
            assert seg == [0, 14, 28]
        finally:
            os.unlink(path)

    def test_plan_output_validates(self):
        """Planner output should pass validator"""
        cfg, path = self._run_plan(
            "ERNIE-4.5-300B-A47B", 16, 80, 8192, 1, "fp8"
        )
        try:
            r = run_cmd(
                f"python3 /app/validator.py validate {path} "
                f"--model ERNIE-4.5-300B-A47B --num-gpus 16"
            )
            assert r.returncode == 0, f"validate failed: {r.stderr}"
            out = json.loads(r.stdout)
            assert out["num_violations"] == 0, (
                f"Planned config has violations: {out['violations']}"
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Pipeline tests: batch validation with yq + jq + sqlite3
# ---------------------------------------------------------------------------

class TestPipeline:
    """Tests for the batch validation pipeline using yq, jq, and sqlite3."""

    @classmethod
    def setup_class(cls):
        """Run the pipeline once before all pipeline tests."""
        for f in ["/app/results.db", "/app/results.report.json"]:
            if os.path.exists(f):
                os.unlink(f)
        cls._result = run_cmd(
            "bash /app/pipeline.sh /app/manifest.yaml /app/results.db",
            timeout=120
        )

    def test_pipeline_succeeds(self):
        """Pipeline script must exit 0"""
        assert self._result.returncode == 0, (
            f"Pipeline failed (rc={self._result.returncode}):\n"
            f"stdout: {self._result.stdout}\n"
            f"stderr: {self._result.stderr}"
        )

    def test_db_exists(self):
        """Pipeline must create the SQLite database file"""
        assert self._result.returncode == 0, "Pipeline did not succeed"
        assert os.path.exists("/app/results.db"), "results.db not created"

    def test_validations_table_count(self):
        """Database must have one validation row per manifest entry (7 total)"""
        assert self._result.returncode == 0, "Pipeline did not succeed"
        r = run_cmd('sqlite3 /app/results.db "SELECT COUNT(*) FROM validations;"')
        assert r.returncode == 0, f"sqlite3 query failed: {r.stderr}"
        assert r.stdout.strip() == "7", (
            f"Expected 7 validations, got {r.stdout.strip()}"
        )

    def test_violations_table_count(self):
        """Database must have 23 total violation rows (5+4+4+4+6 from broken configs)"""
        assert self._result.returncode == 0, "Pipeline did not succeed"
        r = run_cmd('sqlite3 /app/results.db "SELECT COUNT(*) FROM violations;"')
        assert r.returncode == 0, f"sqlite3 query failed: {r.stderr}"
        assert r.stdout.strip() == "23", (
            f"Expected 23 violations, got {r.stdout.strip()}"
        )

    def test_clean_configs_in_db(self):
        """Database must show exactly 2 configs with zero violations"""
        assert self._result.returncode == 0, "Pipeline did not succeed"
        r = run_cmd(
            'sqlite3 /app/results.db '
            '"SELECT COUNT(*) FROM validations WHERE num_violations = 0;"'
        )
        assert r.returncode == 0, f"sqlite3 query failed: {r.stderr}"
        assert r.stdout.strip() == "2", (
            f"Expected 2 clean configs, got {r.stdout.strip()}"
        )

    def test_report_exists(self):
        """Pipeline must produce the aggregate JSON report"""
        assert self._result.returncode == 0, "Pipeline did not succeed"
        assert os.path.exists("/app/results.report.json"), (
            "results.report.json not created"
        )

    def test_report_totals(self):
        """Report must contain correct aggregate totals"""
        assert self._result.returncode == 0, "Pipeline did not succeed"
        with open("/app/results.report.json") as f:
            report = json.load(f)
        assert report["total_configs"] == 7, (
            f"Expected total_configs=7, got {report['total_configs']}"
        )
        assert report["total_violations"] == 23, (
            f"Expected total_violations=23, got {report['total_violations']}"
        )
        assert report["clean_configs"] == 2, (
            f"Expected clean_configs=2, got {report['clean_configs']}"
        )

    def test_report_violation_summary_sorted(self):
        """violation_summary must be sorted by count desc, then rule asc"""
        assert self._result.returncode == 0, "Pipeline did not succeed"
        with open("/app/results.report.json") as f:
            report = json.load(f)
        summary = report["violation_summary"]
        assert len(summary) == 13, (
            f"Expected 13 unique violation rules, got {len(summary)}"
        )
        # Top two rules (count=3 each): MOE_GROUP, PARALLEL_PRODUCT
        assert summary[0]["rule"] == "MOE_GROUP", (
            f"Expected first rule MOE_GROUP, got {summary[0]['rule']}"
        )
        assert summary[0]["count"] == 3
        assert summary[1]["rule"] == "PARALLEL_PRODUCT", (
            f"Expected second rule PARALLEL_PRODUCT, got {summary[1]['rule']}"
        )
        assert summary[1]["count"] == 3
        # Verify descending order
        for i in range(len(summary) - 1):
            assert summary[i]["count"] >= summary[i + 1]["count"], (
                f"Summary not sorted by count desc at index {i}"
            )
            if summary[i]["count"] == summary[i + 1]["count"]:
                assert summary[i]["rule"] < summary[i + 1]["rule"], (
                    f"Summary not sorted by rule asc within count={summary[i]['count']}"
                )

    def test_db_worst_config_query(self):
        """Ad-hoc query: config with most violations should be broken_5 (6 violations)"""
        assert self._result.returncode == 0, "Pipeline did not succeed"
        r = run_cmd(
            'sqlite3 /app/results.db '
            '"SELECT config_file FROM validations '
            'ORDER BY num_violations DESC LIMIT 1;"'
        )
        assert r.returncode == 0, f"sqlite3 query failed: {r.stderr}"
        assert "broken_5" in r.stdout, (
            f"Expected broken_5 as worst config, got {r.stdout.strip()}"
        )
