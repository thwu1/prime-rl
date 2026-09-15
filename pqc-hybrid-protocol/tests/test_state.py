"""
Tests for PQC integration suite.

"""

import json
import os
import subprocess


def run_program(path, timeout=120):
    """Run a compiled program with proper library paths."""
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = "/usr/local/lib:/usr/local/lib64:" + env.get(
        "LD_LIBRARY_PATH", ""
    )
    return subprocess.run(
        [path], capture_output=True, text=True, timeout=timeout, env=env
    )


class TestBuildSystem:
    """Verify liboqs is built and installed correctly."""

    def test_liboqs_shared_library(self):
        result = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True)
        assert "liboqs" in result.stdout, "liboqs shared library not in ldconfig cache"

    def test_liboqs_headers(self):
        found = os.path.isfile("/usr/local/include/oqs/oqs.h") or os.path.isfile(
            "/usr/include/oqs/oqs.h"
        )
        assert found, "oqs/oqs.h header not found"

    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "Makefile not found at /app/Makefile"


class TestKEMExchange:
    """Verify the fixed KEM exchange program."""

    def test_binary_exists(self):
        assert os.path.isfile("/app/broken_kem"), "broken_kem binary not found"
        assert os.access("/app/broken_kem", os.X_OK), "broken_kem not executable"

    def test_runs_successfully(self):
        result = run_program("/app/broken_kem")
        assert result.returncode == 0, f"broken_kem failed with: {result.stderr}"
        assert (
            "KEM_EXCHANGE_SUCCESS" in result.stdout
        ), f"Expected KEM_EXCHANGE_SUCCESS, got: {result.stdout.strip()}"

    def test_output_parameters(self):
        run_program("/app/broken_kem")
        path = "/app/output/kem_result.json"
        assert os.path.isfile(path), f"{path} not found"
        with open(path) as f:
            data = json.load(f)
        assert data["algorithm"] == "ML-KEM-768", f"Wrong algorithm: {data.get('algorithm')}"
        assert data["pk_bytes"] == 1184, f"Wrong pk_bytes: {data.get('pk_bytes')}"
        assert data["ct_bytes"] == 1088, f"Wrong ct_bytes: {data.get('ct_bytes')}"
        assert data["ss_bytes"] == 32, f"Wrong ss_bytes: {data.get('ss_bytes')}"


class TestHybridKEM:
    """Verify the hybrid dual-KEM program."""

    def test_binary_exists(self):
        assert os.path.isfile("/app/hybrid_kem"), "hybrid_kem binary not found"
        assert os.access("/app/hybrid_kem", os.X_OK), "hybrid_kem not executable"

    def test_runs_successfully(self):
        result = run_program("/app/hybrid_kem")
        assert result.returncode == 0, f"hybrid_kem failed with: {result.stderr}"
        assert (
            "HYBRID_KEM_SUCCESS" in result.stdout
        ), f"Expected HYBRID_KEM_SUCCESS, got: {result.stdout.strip()}"

    def test_output_parameters(self):
        run_program("/app/hybrid_kem")
        path = "/app/output/hybrid_result.json"
        assert os.path.isfile(path), f"{path} not found"
        with open(path) as f:
            data = json.load(f)
        assert data["success"] is True, "Hybrid KEM reported failure"
        algs = data["algorithms"]
        assert "ML-KEM-512" in algs, "ML-KEM-512 not in algorithms list"
        assert "ML-KEM-1024" in algs, "ML-KEM-1024 not in algorithms list"
        # ML-KEM-512: pk=800, ct=768; ML-KEM-1024: pk=1568, ct=1568
        assert (
            data["combined_pk_bytes"] == 2368
        ), f"Wrong combined_pk_bytes: {data.get('combined_pk_bytes')} (expected 800+1568=2368)"
        assert (
            data["combined_ct_bytes"] == 2336
        ), f"Wrong combined_ct_bytes: {data.get('combined_ct_bytes')} (expected 768+1568=2336)"
        assert data["ss_bytes"] == 32, f"Wrong ss_bytes: {data.get('ss_bytes')}"


class TestSigMatrix:
    """Verify the signature cross-verification matrix program."""

    def test_binary_exists(self):
        assert os.path.isfile("/app/sig_matrix"), "sig_matrix binary not found"
        assert os.access("/app/sig_matrix", os.X_OK), "sig_matrix not executable"

    def test_runs_successfully(self):
        result = run_program("/app/sig_matrix")
        assert result.returncode == 0, f"sig_matrix failed with: {result.stderr}"
        assert (
            "SIG_MATRIX_COMPLETE" in result.stdout
        ), f"Expected SIG_MATRIX_COMPLETE, got: {result.stdout.strip()}"

    def test_output_structure(self):
        run_program("/app/sig_matrix")
        path = "/app/output/sig_matrix.json"
        assert os.path.isfile(path), f"{path} not found"
        with open(path) as f:
            data = json.load(f)
        assert "results" in data, "Missing 'results' key in sig_matrix.json"
        assert len(data["results"]) == 3, f"Expected 3 results, got {len(data['results'])}"

    def test_mldsa44_params(self):
        run_program("/app/sig_matrix")
        with open("/app/output/sig_matrix.json") as f:
            data = json.load(f)
        r = next((x for x in data["results"] if x["algorithm"] == "ML-DSA-44"), None)
        assert r is not None, "ML-DSA-44 not found in results"
        assert r["correct_key_verify"] is True, "ML-DSA-44 correct key verify failed"
        assert r["wrong_key_verify"] is False, "ML-DSA-44 wrong key verify should fail"
        assert r["pk_bytes"] == 1312, f"ML-DSA-44 pk_bytes={r['pk_bytes']}, expected 1312"
        assert r["sig_bytes"] == 2420, f"ML-DSA-44 sig_bytes={r['sig_bytes']}, expected 2420"
        assert r["nist_level"] == 2, f"ML-DSA-44 nist_level={r['nist_level']}, expected 2"

    def test_mldsa65_params(self):
        run_program("/app/sig_matrix")
        with open("/app/output/sig_matrix.json") as f:
            data = json.load(f)
        r = next((x for x in data["results"] if x["algorithm"] == "ML-DSA-65"), None)
        assert r is not None, "ML-DSA-65 not found in results"
        assert r["correct_key_verify"] is True, "ML-DSA-65 correct key verify failed"
        assert r["wrong_key_verify"] is False, "ML-DSA-65 wrong key verify should fail"
        assert r["pk_bytes"] == 1952, f"ML-DSA-65 pk_bytes={r['pk_bytes']}, expected 1952"
        assert r["sig_bytes"] == 3309, f"ML-DSA-65 sig_bytes={r['sig_bytes']}, expected 3309"
        assert r["nist_level"] == 3, f"ML-DSA-65 nist_level={r['nist_level']}, expected 3"

    def test_mldsa87_params(self):
        run_program("/app/sig_matrix")
        with open("/app/output/sig_matrix.json") as f:
            data = json.load(f)
        r = next((x for x in data["results"] if x["algorithm"] == "ML-DSA-87"), None)
        assert r is not None, "ML-DSA-87 not found in results"
        assert r["correct_key_verify"] is True, "ML-DSA-87 correct key verify failed"
        assert r["wrong_key_verify"] is False, "ML-DSA-87 wrong key verify should fail"
        assert r["pk_bytes"] == 2592, f"ML-DSA-87 pk_bytes={r['pk_bytes']}, expected 2592"
        assert r["sig_bytes"] == 4627, f"ML-DSA-87 sig_bytes={r['sig_bytes']}, expected 4627"
        assert r["nist_level"] == 5, f"ML-DSA-87 nist_level={r['nist_level']}, expected 5"
