
import json
import os

import pytest


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def report():
    path = "/app/audit_report.json"
    assert os.path.exists(path), "audit_report.json not found at /app/"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def model_config():
    with open("/app/model/config.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def activation_profile():
    with open("/app/model/activation_profile.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def vram_profile():
    with open("/app/model/vram_profile.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def gpu_inventory():
    with open("/app/system/gpu_inventory.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def numa_topology():
    with open("/app/system/numa_topology.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def launch_config():
    with open("/app/deploy/launch_config.json") as f:
        return json.load(f)


# ── helpers ─────────────────────────────────────────────────────────────────

def _expert_params(cfg):
    return 3 * cfg["hidden_size"] * cfg["moe_intermediate_size"]


def _expert_memory(cfg):
    params = _expert_params(cfg)
    q = cfg["quantization_config"]
    bits = q["bits"]
    gs = q["group_size"]
    sd = q["scale_dtype"]
    scale_bytes = 2 if sd in ("bfloat16", "float16") else 4
    return params * bits // 8 + (params // gs) * scale_bytes


def _compute_optimal_placement(act, budget):
    counts = act["layer_expert_counts"]
    ranked = []
    for li, layer in enumerate(counts):
        for ei, count in enumerate(layer):
            ranked.append((-count, li, ei))
    ranked.sort()
    placement = {}
    for _, li, ei in ranked[:budget]:
        key = str(li)
        if key not in placement:
            placement[key] = []
        placement[key].append(ei)
    for key in placement:
        placement[key].sort()
    for li in range(len(counts)):
        if str(li) not in placement:
            placement[str(li)] = []
    return placement


def _compute_hit_rate(placement, act):
    counts = act["layer_expert_counts"]
    total = sum(sum(layer) for layer in counts)
    hits = 0
    for ls, experts in placement.items():
        for ei in experts:
            hits += counts[int(ls)][ei]
    return hits / total


# ── hardware capabilities ──────────────────────────────────────────────────

class TestHardwareCapabilities:
    def test_section_exists(self, report):
        assert "hardware_capabilities" in report

    def test_physical_cores_per_socket(self, report):
        assert report["hardware_capabilities"]["physical_cores_per_socket"] == 24

    def test_num_sockets(self, report):
        assert report["hardware_capabilities"]["num_sockets"] == 2

    def test_total_physical_cores(self, report):
        hw = report["hardware_capabilities"]
        assert hw["total_physical_cores"] == 48
        assert hw["total_physical_cores"] == hw["physical_cores_per_socket"] * hw["num_sockets"]

    def test_amx_detected(self, report):
        assert report["hardware_capabilities"]["has_amx"] is True

    def test_avx512_detected(self, report):
        assert report["hardware_capabilities"]["has_avx512"] is True

    def test_avx512_vnni_detected(self, report):
        assert report["hardware_capabilities"]["has_avx512_vnni"] is True

    def test_avx512_bf16_detected(self, report):
        assert report["hardware_capabilities"]["has_avx512_bf16"] is True

    def test_avx512_vbmi_detected(self, report):
        assert report["hardware_capabilities"]["has_avx512_vbmi"] is True

    def test_optimal_kernel_variant(self, report):
        variant = report["hardware_capabilities"]["optimal_kernel_variant"].lower()
        assert variant == "amx", (
            f"With AMX available, optimal variant should be 'amx', got '{variant}'"
        )

    def test_numa_node_count(self, report, numa_topology):
        expected = len(numa_topology["nodes"])
        assert report["hardware_capabilities"]["numa_node_count"] == expected

    def test_total_system_memory(self, report, numa_topology):
        expected_mb = sum(n["memory_mb"] for n in numa_topology["nodes"])
        assert report["hardware_capabilities"]["total_system_memory_mb"] == expected_mb

    def test_gpu_count(self, report, gpu_inventory):
        expected = len(gpu_inventory["gpus"])
        assert report["hardware_capabilities"]["gpu_count"] == expected

    def test_gpu_vram(self, report, gpu_inventory):
        expected = gpu_inventory["gpus"][0]["vram_bytes"]
        assert report["hardware_capabilities"]["gpu_vram_bytes"] == expected


# ── memory analysis ────────────────────────────────────────────────────────

class TestMemoryAnalysis:
    def test_section_exists(self, report):
        assert "memory_analysis" in report

    def test_expert_param_count(self, report, model_config):
        expected = _expert_params(model_config)
        assert expected == 25165824, "sanity: expected expert params"
        assert report["memory_analysis"]["expert_param_count"] == expected

    def test_expert_memory_bytes(self, report, model_config):
        expected = _expert_memory(model_config)
        assert expected == 25559040, "sanity: expected expert memory"
        assert report["memory_analysis"]["expert_memory_bytes"] == expected

    def test_non_expert_vram(self, report, vram_profile):
        expected = sum(vram_profile["components"].values())
        assert expected == 25000000000, "sanity: expected non-expert VRAM"
        assert report["memory_analysis"]["non_expert_vram_bytes"] == expected

    def test_available_expert_vram(self, report, gpu_inventory, vram_profile):
        gpu_vram = gpu_inventory["gpus"][0]["vram_bytes"]
        non_expert = sum(vram_profile["components"].values())
        expected = gpu_vram - non_expert
        assert expected == 769803776, "sanity: expected available VRAM"
        assert report["memory_analysis"]["available_expert_vram_bytes"] == expected

    def test_max_gpu_experts(self, report, model_config, gpu_inventory, vram_profile):
        em = _expert_memory(model_config)
        available = gpu_inventory["gpus"][0]["vram_bytes"] - sum(vram_profile["components"].values())
        expected = available // em
        assert expected == 30, "sanity: expected max experts"
        assert report["memory_analysis"]["max_gpu_experts"] == expected


# ── configuration issues ───────────────────────────────────────────────────

class TestConfigurationIssues:
    def _params(self, report):
        return {
            i["parameter"].lower().replace("-", "_")
            for i in report["configuration_issues"]
        }

    def _all_text(self, report):
        return " ".join(
            f"{i['parameter']} {i.get('problem', '')} {i.get('current_value', '')}"
            for i in report["configuration_issues"]
        ).lower()

    def test_section_exists(self, report):
        assert "configuration_issues" in report

    def test_minimum_issues_found(self, report):
        assert len(report["configuration_issues"]) >= 5, (
            f"Expected >= 5 config issues, found {len(report['configuration_issues'])}"
        )

    def test_method_mismatch_detected(self, report):
        params = self._params(report)
        assert "kt_method" in params, "Should flag kt_method mismatch (BF16 vs FP8)"

    def test_gpu_experts_issue_detected(self, report):
        params = self._params(report)
        found = any("gpu" in p and "expert" in p for p in params)
        assert found, "Should flag kt_num_gpu_experts exceeding VRAM budget"

    def test_cpuinfer_issue_detected(self, report):
        params = self._params(report)
        found = any("cpuinfer" in p for p in params)
        assert found, "Should flag kt_cpuinfer exceeding physical core count"

    def test_threadpool_issue_detected(self, report):
        params = self._params(report)
        found = any("threadpool" in p or "thread_pool" in p for p in params)
        assert found, "Should flag kt_threadpool_count not matching NUMA node count"

    def test_token_budget_issue_detected(self, report):
        params = self._params(report)
        text = self._all_text(report)
        has_prefill = any("prefill" in p or "chunk" in p for p in params)
        has_running = any("running" in p for p in params)
        has_token_text = "token" in text or "cache" in text or "exceed" in text
        assert has_prefill or has_running or has_token_text, (
            "Should flag token budget violation "
            "(chunked_prefill_size > max_total_tokens or "
            "max_running_requests * max_new_tokens > max_total_tokens)"
        )


# ── expert placement ───────────────────────────────────────────────────────

class TestExpertPlacement:
    def test_section_exists(self, report):
        assert "expert_placement" in report

    def test_total_experts(self, report, model_config):
        expected = model_config["num_moe_layers"] * model_config["num_experts_per_layer"]
        assert expected == 96, "sanity: 8 layers * 12 experts"
        assert report["expert_placement"]["total_experts"] == expected

    def test_gpu_expert_budget(self, report):
        assert report["expert_placement"]["gpu_expert_budget"] == 30

    def test_placement_has_all_layers(self, report, model_config):
        placement = report["expert_placement"]["optimal_placement"]
        for li in range(model_config["num_moe_layers"]):
            assert str(li) in placement, f"Layer {li} missing from placement"

    def test_placement_total_count(self, report):
        placement = report["expert_placement"]["optimal_placement"]
        total = sum(len(v) for v in placement.values())
        assert total == 30, f"Expected 30 placed experts, got {total}"

    def test_placement_indices_sorted(self, report):
        for layer, experts in report["expert_placement"]["optimal_placement"].items():
            assert experts == sorted(experts), f"Layer {layer}: experts not sorted"

    def test_placement_indices_valid(self, report, model_config):
        ne = model_config["num_experts_per_layer"]
        for layer, experts in report["expert_placement"]["optimal_placement"].items():
            for e in experts:
                assert 0 <= e < ne, f"Layer {layer}: invalid expert index {e}"

    def test_placement_no_duplicates(self, report):
        for layer, experts in report["expert_placement"]["optimal_placement"].items():
            assert len(experts) == len(set(experts)), f"Layer {layer}: duplicate experts"

    def test_placement_matches_optimal(self, report, activation_profile):
        expected = _compute_optimal_placement(activation_profile, 30)
        actual = report["expert_placement"]["optimal_placement"]
        assert actual == expected, (
            f"Placement does not match optimal top-30 assignment:\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual}"
        )

    def test_hit_rate_correct(self, report, activation_profile):
        placement = _compute_optimal_placement(activation_profile, 30)
        expected = _compute_hit_rate(placement, activation_profile)
        actual = report["expert_placement"]["optimal_hit_rate"]
        assert abs(actual - expected) < 1e-4, (
            f"Hit rate mismatch: expected {expected:.6f}, got {actual}"
        )

    def test_hit_rate_in_range(self, report):
        rate = report["expert_placement"]["optimal_hit_rate"]
        assert 0.0 <= rate <= 1.0, f"Hit rate {rate} out of [0, 1]"

    def test_no_better_swap_exists(self, report, activation_profile):
        """Every GPU-placed expert should have count >= every non-placed expert."""
        placement = report["expert_placement"]["optimal_placement"]
        counts = activation_profile["layer_expert_counts"]
        ne = len(counts[0])

        gpu_counts = []
        cpu_counts = []
        for li, layer in enumerate(counts):
            placed = set(placement.get(str(li), []))
            for ei in range(ne):
                if ei in placed:
                    gpu_counts.append(layer[ei])
                else:
                    cpu_counts.append(layer[ei])

        if gpu_counts and cpu_counts:
            assert min(gpu_counts) >= max(cpu_counts), (
                f"Suboptimal: min GPU count {min(gpu_counts)} < "
                f"max CPU count {max(cpu_counts)}"
            )
