
"""
Test performance incident forensics diagnosis and flame graph output.
Verifies /app/diagnosis.json fields and /app/flamegraph.svg validity.
"""

import json
import os
import pytest

DIAGNOSIS_PATH = "/app/diagnosis.json"
FLAMEGRAPH_PATH = "/app/flamegraph.svg"

EXPECTED = {
    "cpu_bottleneck_function": "__futex_wait_queue",
    "cpu_bottleneck_percentage": 16.71,
    "pathological_pid": 7293,
    "pathological_syscall_count": 1847,
    "memory_leak_pid": 3156,
    "memory_growth_kb": 153600,
    "disk_bottleneck_device": "sdb",
    "disk_queue_depth": 8.53,
    "network_error_interface": "eth1",
    "network_error_count": 2400,
    "root_cause_pid": 3156,
    "causal_chain": ["memory_leak", "disk_saturation", "cpu_contention"],
}

FLOAT_EPSILON = 0.02


@pytest.fixture
def diagnosis():
    assert os.path.exists(DIAGNOSIS_PATH), (
        f"Diagnosis file not found at {DIAGNOSIS_PATH}"
    )
    with open(DIAGNOSIS_PATH) as f:
        data = json.load(f)
    return data


# ── Flame graph tests ────────────────────────────────────────────────────

class TestFlameGraph:
    def test_flamegraph_exists(self):
        assert os.path.exists(FLAMEGRAPH_PATH), (
            f"Flame graph SVG not found at {FLAMEGRAPH_PATH}"
        )

    def test_flamegraph_is_valid_svg(self):
        with open(FLAMEGRAPH_PATH) as f:
            content = f.read()
        assert "<svg" in content.lower(), "File does not contain valid SVG markup"
        assert len(content) > 1000, (
            f"SVG file too small ({len(content)} bytes), likely not a real flame graph"
        )

    def test_flamegraph_contains_profile_data(self):
        with open(FLAMEGRAPH_PATH) as f:
            content = f.read()
        known_funcs = [
            "server_main", "request_handler", "__futex_wait_queue",
            "db_query", "deflate_slow",
        ]
        found = any(fn in content for fn in known_funcs)
        assert found, (
            "Flame graph does not contain any expected function names from the "
            "profiling data — it may not have been generated from the incident data"
        )


# ── CPU bottleneck tests ─────────────────────────────────────────────────

def test_cpu_bottleneck_function(diagnosis):
    assert diagnosis["cpu_bottleneck_function"] == EXPECTED["cpu_bottleneck_function"], (
        f"Expected {EXPECTED['cpu_bottleneck_function']}, "
        f"got {diagnosis['cpu_bottleneck_function']}"
    )


def test_cpu_bottleneck_percentage(diagnosis):
    actual = float(diagnosis["cpu_bottleneck_percentage"])
    expected = EXPECTED["cpu_bottleneck_percentage"]
    assert abs(actual - expected) < FLOAT_EPSILON, (
        f"Expected ~{expected}, got {actual}"
    )


# ── Pathological syscall tests ───────────────────────────────────────────

def test_pathological_pid(diagnosis):
    assert int(diagnosis["pathological_pid"]) == EXPECTED["pathological_pid"], (
        f"Expected {EXPECTED['pathological_pid']}, "
        f"got {diagnosis['pathological_pid']}"
    )


def test_pathological_syscall_count(diagnosis):
    assert int(diagnosis["pathological_syscall_count"]) == EXPECTED["pathological_syscall_count"], (
        f"Expected {EXPECTED['pathological_syscall_count']}, "
        f"got {diagnosis['pathological_syscall_count']}"
    )


# ── Memory leak tests ───────────────────────────────────────────────────

def test_memory_leak_pid(diagnosis):
    assert int(diagnosis["memory_leak_pid"]) == EXPECTED["memory_leak_pid"], (
        f"Expected {EXPECTED['memory_leak_pid']}, "
        f"got {diagnosis['memory_leak_pid']}"
    )


def test_memory_growth_kb(diagnosis):
    assert int(diagnosis["memory_growth_kb"]) == EXPECTED["memory_growth_kb"], (
        f"Expected {EXPECTED['memory_growth_kb']}, "
        f"got {diagnosis['memory_growth_kb']}"
    )


# ── Disk bottleneck tests ───────────────────────────────────────────────

def test_disk_bottleneck_device(diagnosis):
    assert diagnosis["disk_bottleneck_device"] == EXPECTED["disk_bottleneck_device"], (
        f"Expected {EXPECTED['disk_bottleneck_device']}, "
        f"got {diagnosis['disk_bottleneck_device']}"
    )


def test_disk_queue_depth(diagnosis):
    actual = float(diagnosis["disk_queue_depth"])
    expected = EXPECTED["disk_queue_depth"]
    assert abs(actual - expected) < FLOAT_EPSILON, (
        f"Expected ~{expected}, got {actual}"
    )


# ── Network error tests ─────────────────────────────────────────────────

def test_network_error_interface(diagnosis):
    assert diagnosis["network_error_interface"] == EXPECTED["network_error_interface"], (
        f"Expected {EXPECTED['network_error_interface']}, "
        f"got {diagnosis['network_error_interface']}"
    )


def test_network_error_count(diagnosis):
    assert int(diagnosis["network_error_count"]) == EXPECTED["network_error_count"], (
        f"Expected {EXPECTED['network_error_count']}, "
        f"got {diagnosis['network_error_count']}"
    )


# ── Root cause and causal chain tests ────────────────────────────────────

def test_root_cause_pid(diagnosis):
    assert int(diagnosis["root_cause_pid"]) == EXPECTED["root_cause_pid"], (
        f"Expected root cause PID {EXPECTED['root_cause_pid']}, "
        f"got {diagnosis['root_cause_pid']}"
    )


def test_causal_chain(diagnosis):
    chain = diagnosis["causal_chain"]
    expected = EXPECTED["causal_chain"]
    assert isinstance(chain, list), f"causal_chain must be a list, got {type(chain)}"
    assert chain == expected, (
        f"Expected causal chain {expected}, got {chain}. "
        f"Chain must include only causally linked failures in correct order."
    )
