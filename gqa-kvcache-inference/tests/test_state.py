
"""
Tests for optimized autoregressive generation and performance profiling.
Verifies correctness (token-for-token match) and profiling artifact validity.
"""

import json
import os
import subprocess
import sys

import torch

sys.path.insert(0, "/app")

from model import LLMModel, MODEL_CONFIG, generate_simple


def _make_model(seed=42):
    torch.manual_seed(seed)
    model = LLMModel(MODEL_CONFIG)
    model.eval()
    return model


class TestOptimizedGeneration:

    def test_can_import(self):
        """kv_inference module must be importable with required exports."""
        from kv_inference import KVCache, generate_cached
        assert callable(KVCache)
        assert callable(generate_cached)

    def test_short_prompt_10_tokens(self):
        """5-token prompt, generate 10 tokens: optimized must match baseline exactly."""
        model = _make_model(42)
        prompt = torch.tensor([[1, 50, 100, 200, 3]])
        expected = generate_simple(model, prompt.clone(), 10)
        from kv_inference import generate_cached
        actual = generate_cached(model, prompt.clone(), 10)
        assert torch.equal(expected, actual), (
            f"Token mismatch.\nExpected: {expected.tolist()}\nActual:   {actual.tolist()}"
        )

    def test_single_token_prompt(self):
        """Single-token prompt, generate 15 tokens."""
        model = _make_model(42)
        prompt = torch.tensor([[42]])
        expected = generate_simple(model, prompt.clone(), 15)
        from kv_inference import generate_cached
        actual = generate_cached(model, prompt.clone(), 15)
        assert torch.equal(expected, actual), (
            f"Token mismatch for single-token prompt.\n"
            f"Expected: {expected.tolist()}\nActual:   {actual.tolist()}"
        )

    def test_long_prompt(self):
        """50-token prompt, generate 20 tokens."""
        model = _make_model(42)
        prompt = torch.tensor([[i % MODEL_CONFIG["vocab_size"] for i in range(50)]])
        expected = generate_simple(model, prompt.clone(), 20)
        from kv_inference import generate_cached
        actual = generate_cached(model, prompt.clone(), 20)
        assert torch.equal(expected, actual), (
            f"Token mismatch for 50-token prompt.\n"
            f"Expected last 25: {expected[0, -25:].tolist()}\n"
            f"Actual   last 25: {actual[0, -25:].tolist()}"
        )

    def test_extended_generation(self):
        """5-token prompt, generate 40 tokens."""
        model = _make_model(42)
        prompt = torch.tensor([[7, 14, 21, 28, 35]])
        expected = generate_simple(model, prompt.clone(), 40)
        from kv_inference import generate_cached
        actual = generate_cached(model, prompt.clone(), 40)
        assert torch.equal(expected, actual), (
            f"Token mismatch during extended generation.\n"
            f"First divergence at token index "
            f"{(expected != actual).nonzero(as_tuple=True)[1][0].item() if not torch.equal(expected, actual) else 'N/A'}"
        )

    def test_near_context_limit(self):
        """Prompt + generation fills almost entire context window (200 + 50 = 250 < 256)."""
        model = _make_model(42)
        prompt_len = 200
        gen_len = 50
        prompt = torch.tensor([[i % MODEL_CONFIG["vocab_size"] for i in range(prompt_len)]])
        expected = generate_simple(model, prompt.clone(), gen_len)
        from kv_inference import generate_cached
        actual = generate_cached(model, prompt.clone(), gen_len)
        assert torch.equal(expected, actual), (
            f"Token mismatch near context limit.\n"
            f"Expected shape: {expected.shape}, Actual shape: {actual.shape}"
        )

    def test_different_model_seeds(self):
        """Must produce correct results across different model initializations."""
        from kv_inference import generate_cached
        for seed in [0, 99, 12345]:
            model = _make_model(seed)
            prompt = torch.tensor([[7, 14, 21]])
            expected = generate_simple(model, prompt.clone(), 10)
            actual = generate_cached(model, prompt.clone(), 10)
            assert torch.equal(expected, actual), (
                f"Token mismatch with model seed={seed}.\n"
                f"Expected: {expected.tolist()}\nActual:   {actual.tolist()}"
            )

    def test_output_shape(self):
        """Output shape must be (1, prompt_len + max_new_tokens)."""
        model = _make_model(42)
        prompt = torch.tensor([[1, 2, 3, 4, 5]])
        from kv_inference import generate_cached
        result = generate_cached(model, prompt.clone(), 10)
        assert result.shape == (1, 15), f"Expected shape (1, 15), got {result.shape}"

    def test_prompt_preserved(self):
        """Output must begin with the original prompt tokens."""
        model = _make_model(42)
        prompt = torch.tensor([[10, 20, 30, 40, 50]])
        from kv_inference import generate_cached
        result = generate_cached(model, prompt.clone(), 10)
        assert torch.equal(result[:, :5], prompt), (
            f"Prompt not preserved.\n"
            f"Expected prefix: {prompt.tolist()}\n"
            f"Got prefix:      {result[:, :5].tolist()}"
        )


class TestProfilingBenchmark:
    """Tests for performance profiling and benchmarking artifacts."""

    @classmethod
    def setup_class(cls):
        """Run profile_report.py once before all profiling tests."""
        cls._script_path = "/app/profile_report.py"
        cls._script_exists = os.path.isfile(cls._script_path)
        cls._run_result = None
        if cls._script_exists:
            cls._run_result = subprocess.run(
                ["python3", cls._script_path],
                capture_output=True, text=True, timeout=120,
            )

    def test_profile_script_exists(self):
        """profile_report.py must exist at /app/"""
        assert self._script_exists, (
            "profile_report.py not found at /app/profile_report.py"
        )

    def test_profile_script_succeeds(self):
        """profile_report.py must execute without errors."""
        assert self._run_result is not None, "profile_report.py not found"
        assert self._run_result.returncode == 0, (
            f"profile_report.py failed (exit {self._run_result.returncode}):\n"
            f"{self._run_result.stderr[-1000:]}"
        )

    def test_baseline_trace_valid_chrome_format(self):
        """baseline.json must be valid Chrome trace-format JSON."""
        path = "/app/traces/baseline.json"
        assert os.path.isfile(path), "baseline.json trace not found at /app/traces/"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict), "baseline.json must be a JSON object"
        assert "traceEvents" in data, (
            "baseline.json missing 'traceEvents' key — not Chrome trace format"
        )
        assert isinstance(data["traceEvents"], list), "'traceEvents' must be a list"
        assert len(data["traceEvents"]) > 0, "baseline.json has empty traceEvents"

    def test_optimized_trace_valid_chrome_format(self):
        """optimized.json must be valid Chrome trace-format JSON."""
        path = "/app/traces/optimized.json"
        assert os.path.isfile(path), "optimized.json trace not found at /app/traces/"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict), "optimized.json must be a JSON object"
        assert "traceEvents" in data, (
            "optimized.json missing 'traceEvents' key — not Chrome trace format"
        )
        assert isinstance(data["traceEvents"], list), "'traceEvents' must be a list"
        assert len(data["traceEvents"]) > 0, "optimized.json has empty traceEvents"

    def test_benchmark_results_structure(self):
        """benchmark_results.json must contain required keys with numeric values."""
        path = "/app/benchmark_results.json"
        assert os.path.isfile(path), "benchmark_results.json not found at /app/"
        with open(path) as f:
            data = json.load(f)
        required_keys = ["baseline_mean_ms", "optimized_mean_ms", "speedup_ratio"]
        for key in required_keys:
            assert key in data, f"benchmark_results.json missing key: '{key}'"
            assert isinstance(data[key], (int, float)), (
                f"Key '{key}' must be numeric, got {type(data[key]).__name__}"
            )
        assert data["baseline_mean_ms"] > 0, "baseline_mean_ms must be positive"
        assert data["optimized_mean_ms"] > 0, "optimized_mean_ms must be positive"

    def test_benchmark_shows_speedup(self):
        """Optimization must actually be faster than baseline."""
        path = "/app/benchmark_results.json"
        assert os.path.isfile(path), "benchmark_results.json not found"
        with open(path) as f:
            data = json.load(f)
        assert "speedup_ratio" in data, "missing speedup_ratio key"
        assert data["speedup_ratio"] > 1.0, (
            f"Optimization must be faster than baseline, "
            f"but speedup_ratio={data['speedup_ratio']:.3f}"
        )
