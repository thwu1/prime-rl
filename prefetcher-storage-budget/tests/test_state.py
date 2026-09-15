
import json
import math
import os
import subprocess
import pytest


class TestBudgetsFileExists:
    def test_budgets_json_exists(self):
        assert os.path.isfile("/app/budgets.json"), "budgets.json not found"

    def test_budgets_json_valid(self):
        with open("/app/budgets.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)


class TestBudgetsContent:
    @pytest.fixture(autouse=True)
    def load_budgets(self):
        with open("/app/budgets.json") as f:
            self.data = json.load(f)

    def test_has_all_prefetchers(self):
        for key in ["DJOLT", "PIPS", "FNLMMA"]:
            assert key in self.data, f"Missing key: {key}"

    def test_djolt_total_bits(self):
        assert self.data["DJOLT"]["total_bits"] == 956802

    def test_djolt_under_budget(self):
        assert self.data["DJOLT"]["under_128kb"] is True

    def test_pips_total_bits(self):
        assert self.data["PIPS"]["total_bits"] == 1033600

    def test_pips_under_budget(self):
        assert self.data["PIPS"]["under_128kb"] is True

    def test_fnlmma_total_bits(self):
        assert self.data["FNLMMA"]["total_bits"] == 793714

    def test_fnlmma_under_budget(self):
        assert self.data["FNLMMA"]["under_128kb"] is True

    def test_budget_ordering(self):
        """FNL+MMA uses least storage, D-JOLT in middle, PIPS most"""
        assert self.data["FNLMMA"]["total_bits"] < self.data["DJOLT"]["total_bits"]
        assert self.data["DJOLT"]["total_bits"] < self.data["PIPS"]["total_bits"]


class TestCostModelBinary:
    """Verify the compiled D-JOLT cost model C++ binary"""

    def _ensure_compiled(self):
        binary = "/app/djolt_cost_model"
        source = "/app/djolt_cost_model.cpp"
        assert os.path.isfile(source), "djolt_cost_model.cpp not found at /app/"
        if not os.path.isfile(binary) or os.path.getmtime(source) > os.path.getmtime(binary):
            result = subprocess.run(
                ["g++", "-std=c++17", "-O2", "-o", binary, source],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"

    def _run_model(self, lr, sr, ex):
        self._ensure_compiled()
        result = subprocess.run(
            ["/app/djolt_cost_model", str(lr), str(sr), str(ex)],
            capture_output=True, text=True, timeout=10
        )
        return result

    def test_source_exists(self):
        assert os.path.isfile("/app/djolt_cost_model.cpp")

    def test_compiles_successfully(self):
        self._ensure_compiled()
        assert os.path.isfile("/app/djolt_cost_model")

    def test_original_djolt_config(self):
        """Original D-JOLT config from source: lr=2048, sr=1024, ex=128"""
        result = self._run_model(2048, 1024, 128)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert int(result.stdout.strip()) == 956802

    def test_config_128kb_optimal(self):
        """128KB optimal: lr=2048, sr=1024, ex=256 must yield 995,714 bits"""
        result = self._run_model(2048, 1024, 256)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        bits = int(result.stdout.strip())
        assert bits == 995714
        assert bits <= 1048576

    def test_config_160kb_optimal(self):
        """160KB optimal: lr=4096, sr=256, ex=64 must yield 1,298,562 bits"""
        result = self._run_model(4096, 256, 64)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        bits = int(result.stdout.strip())
        assert bits == 1298562
        assert bits <= 1310720

    def test_config_192kb_optimal(self):
        """192KB optimal: lr=4096, sr=1024, ex=128 must yield 1,546,626 bits"""
        result = self._run_model(4096, 1024, 128)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        bits = int(result.stdout.strip())
        assert bits == 1546626
        assert bits <= 1572864

    def test_minimum_config(self):
        """All-minimum: lr=64, sr=64, ex=64 must yield 64,130 bits"""
        result = self._run_model(64, 64, 64)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert int(result.stdout.strip()) == 64130

    def test_large_single_table(self):
        """lr=4194304 (2^22), sr=64, ex=64: tag=1 bit, should succeed"""
        result = self._run_model(4194304, 64, 64)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        bits = int(result.stdout.strip())
        # per_entry for 2^22: tag=1, (4+18+8)*2+2=62, total=63
        # per_entry for 64: tag=17, 62, total=79
        expected = 63 * 4194304 * 4 + 79 * 64 * 4 * 2 + 3458
        assert bits == expected

    def test_reject_not_power_of_two(self):
        result = self._run_model(100, 64, 64)
        assert result.returncode == 1

    def test_reject_below_minimum(self):
        result = self._run_model(32, 64, 64)
        assert result.returncode == 1

    def test_reject_zero_tag_bits(self):
        """2^23 = 8388608 -> tag = 23-23 = 0 -> invalid"""
        result = self._run_model(8388608, 64, 64)
        assert result.returncode == 1

    def test_reject_negative_tag_bits(self):
        """2^24 -> tag = 23-24 = -1 -> invalid"""
        result = self._run_model(16777216, 64, 64)
        assert result.returncode == 1

    def test_permutation_symmetry(self):
        """Total cost is additive over tables, so permutations give equal totals"""
        r1 = self._run_model(2048, 256, 128)
        r2 = self._run_model(256, 2048, 128)
        r3 = self._run_model(128, 256, 2048)
        for r in [r1, r2, r3]:
            assert r.returncode == 0
        v1 = int(r1.stdout.strip())
        v2 = int(r2.stdout.strip())
        v3 = int(r3.stdout.strip())
        assert v1 == v2 == v3


class TestOptimalConfigsFileExists:
    def test_exists(self):
        assert os.path.isfile("/app/optimal_configs.json"), "optimal_configs.json not found"

    def test_valid_json(self):
        with open("/app/optimal_configs.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)


class TestOptimalConfigs:
    @pytest.fixture(autouse=True)
    def load_configs(self):
        with open("/app/optimal_configs.json") as f:
            self.data = json.load(f)

    def test_has_all_budgets(self):
        for key in ["128kb", "160kb", "192kb"]:
            assert key in self.data, f"Missing budget key: {key}"

    def _validate_config(self, config, budget_bits):
        for key in ["lr_sets", "sr_sets", "extra_sets", "total_entries", "total_bits"]:
            assert key in config, f"Missing key: {key}"
        for key in ["lr_sets", "sr_sets", "extra_sets"]:
            val = config[key]
            assert val >= 64, f"{key}={val} < 64"
            assert val & (val - 1) == 0, f"{key}={val} not power of 2"
            log2_val = 0
            s = val
            while s > 1:
                s >>= 1
                log2_val += 1
            assert 23 - log2_val > 0, f"{key}={val}: non-positive tag bits"
        assert config["total_entries"] == (config["lr_sets"] + config["sr_sets"] + config["extra_sets"]) * 4
        assert 0 < config["total_bits"] <= budget_bits

    def test_128kb_config(self):
        c = self.data["128kb"]
        self._validate_config(c, 1048576)
        assert c["lr_sets"] == 2048
        assert c["sr_sets"] == 1024
        assert c["extra_sets"] == 256
        assert c["total_entries"] == 13312

    def test_160kb_config(self):
        c = self.data["160kb"]
        self._validate_config(c, 1310720)
        assert c["lr_sets"] == 4096
        assert c["sr_sets"] == 256
        assert c["extra_sets"] == 64
        assert c["total_entries"] == 17664

    def test_192kb_config(self):
        c = self.data["192kb"]
        self._validate_config(c, 1572864)
        assert c["lr_sets"] == 4096
        assert c["sr_sets"] == 1024
        assert c["extra_sets"] == 128
        assert c["total_entries"] == 20992

    def test_128kb_total_bits(self):
        assert self.data["128kb"]["total_bits"] == 995714

    def test_160kb_total_bits(self):
        assert self.data["160kb"]["total_bits"] == 1298562

    def test_192kb_total_bits(self):
        assert self.data["192kb"]["total_bits"] == 1546626

    def test_optimality_exhaustive(self):
        """Brute-force verify no valid configuration beats ours for any budget"""
        sig_bits = 23
        n_ways = 4
        n_vectors = 2
        vector_size = 8
        ubp_bits = 4
        lru_bits = 2
        # Fixed costs: LR siggen(259) + LR sigqueue(280) + SR siggen(162) +
        # SR sigqueue(94) + upper bit table(615) + training(1040) + monitoring(1008)
        fixed_bits = 259 + 280 + 162 + 94 + 615 + 1040 + 1008  # 3458

        def table_cost(n_sets):
            l2 = 0
            s = n_sets
            while s > 1:
                s >>= 1
                l2 += 1
            tag = sig_bits - l2
            if tag <= 0:
                return float('inf')
            per_entry = tag + (ubp_bits + 18 + vector_size) * n_vectors + lru_bits
            return per_entry * n_sets * n_ways

        powers = [1 << i for i in range(6, 23)]
        budgets = {"128kb": 1048576, "160kb": 1310720, "192kb": 1572864}

        for budget_name, budget_bits in budgets.items():
            our_entries = self.data[budget_name]["total_entries"]
            for lr in powers:
                lc = table_cost(lr)
                if lc + fixed_bits >= budget_bits:
                    continue
                for sr in powers:
                    sc = table_cost(sr)
                    if lc + sc + fixed_bits >= budget_bits:
                        continue
                    for ex in powers:
                        ec = table_cost(ex)
                        if lc + sc + ec + fixed_bits <= budget_bits:
                            entries = (lr + sr + ex) * n_ways
                            assert entries <= our_entries, (
                                f"[{budget_name}] Better config found: lr={lr}, sr={sr}, "
                                f"ex={ex}, entries={entries} > {our_entries}"
                            )
