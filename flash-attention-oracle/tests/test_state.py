
import json
import os
import pytest


@pytest.fixture(scope="session")
def report():
    path = "/app/report.json"
    assert os.path.exists(path), f"Report not found at {path}"
    with open(path) as f:
        data = json.load(f)
    assert "nodes" in data, "Report missing 'nodes' key"
    assert "ranking" in data, "Report missing 'ranking' key"
    assert "build_priority" in data, "Report missing 'build_priority' key"
    assert "deployment_plan" in data, "Report missing 'deployment_plan' key"
    assert "performance_analysis" in data, "Report missing 'performance_analysis' key"
    return data


# --- Structure ---

class TestStructure:
    def test_all_nodes_present(self, report):
        expected = {"ampere-a100", "ampere-a10", "hopper-h100", "blackwell-b200", "thor-gh200"}
        assert set(report["nodes"].keys()) == expected

    def test_all_workloads_present(self, report):
        expected = {"llama-7b-short", "llama-70b-long", "bert-classifier"}
        for node_name, node_data in report["nodes"].items():
            assert set(node_data["workloads"].keys()) == expected, \
                f"Node {node_name} missing workloads"

    def test_deployment_plan_workloads(self, report):
        expected = {"llama-7b-short", "llama-70b-long", "bert-classifier"}
        assert set(report["deployment_plan"].keys()) == expected


# --- Gencode Flags ---

class TestGencodeFlags:
    def test_ampere_a100(self, report):
        flags = report["nodes"]["ampere-a100"]["gencode_flags"]
        assert flags == [
            "-gencode", "arch=compute_80,code=sm_80",
            "-gencode", "arch=compute_90,code=sm_90",
            "-gencode", "arch=compute_90,code=compute_90",
        ]

    def test_ampere_a10(self, report):
        flags = report["nodes"]["ampere-a10"]["gencode_flags"]
        assert flags == [
            "-gencode", "arch=compute_80,code=sm_80",
            "-gencode", "arch=compute_90,code=sm_90",
            "-gencode", "arch=compute_90,code=compute_90",
        ]

    def test_hopper_h100(self, report):
        flags = report["nodes"]["hopper-h100"]["gencode_flags"]
        assert flags == [
            "-gencode", "arch=compute_80,code=sm_80",
            "-gencode", "arch=compute_90,code=sm_90",
            "-gencode", "arch=compute_100,code=sm_100",
            "-gencode", "arch=compute_100,code=compute_100",
        ]

    def test_blackwell_b200(self, report):
        flags = report["nodes"]["blackwell-b200"]["gencode_flags"]
        assert flags == [
            "-gencode", "arch=compute_80,code=sm_80",
            "-gencode", "arch=compute_90,code=sm_90",
            "-gencode", "arch=compute_100f,code=sm_100",
            "-gencode", "arch=compute_120f,code=sm_120",
            "-gencode", "arch=compute_120,code=compute_120",
        ]

    def test_thor_gh200(self, report):
        flags = report["nodes"]["thor-gh200"]["gencode_flags"]
        assert flags == [
            "-gencode", "arch=compute_80,code=sm_80",
            "-gencode", "arch=compute_90,code=sm_90",
            "-gencode", "arch=compute_100,code=sm_100",
            "-gencode", "arch=compute_101,code=sm_101",
            "-gencode", "arch=compute_110,code=compute_110",
        ]


# --- Max Build Jobs ---

class TestMaxBuildJobs:
    def test_ampere_a100(self, report):
        assert report["nodes"]["ampere-a100"]["max_build_jobs"] == 12

    def test_ampere_a10(self, report):
        assert report["nodes"]["ampere-a10"]["max_build_jobs"] == 6

    def test_hopper_h100(self, report):
        assert report["nodes"]["hopper-h100"]["max_build_jobs"] == 25

    def test_blackwell_b200(self, report):
        assert report["nodes"]["blackwell-b200"]["max_build_jobs"] == 51

    def test_thor_gh200(self, report):
        assert report["nodes"]["thor-gh200"]["max_build_jobs"] == 24


# --- Estimated Build Time ---

class TestEstimatedBuildTime:
    def test_ampere_a100(self, report):
        assert report["nodes"]["ampere-a100"]["estimated_build_time_minutes"] == pytest.approx(10.0, abs=0.05)

    def test_ampere_a10(self, report):
        assert report["nodes"]["ampere-a10"]["estimated_build_time_minutes"] == pytest.approx(20.0, abs=0.05)

    def test_hopper_h100(self, report):
        assert report["nodes"]["hopper-h100"]["estimated_build_time_minutes"] == pytest.approx(6.4, abs=0.05)

    def test_blackwell_b200(self, report):
        assert report["nodes"]["blackwell-b200"]["estimated_build_time_minutes"] == pytest.approx(3.9, abs=0.05)

    def test_thor_gh200(self, report):
        assert report["nodes"]["thor-gh200"]["estimated_build_time_minutes"] == pytest.approx(8.3, abs=0.05)


# --- Kernel Block N ---

class TestKernelBlockN:
    def test_a100_llama7b(self, report):
        bn = report["nodes"]["ampere-a100"]["workloads"]["llama-7b-short"]["kernel_block_n"]
        assert bn == 64

    def test_a10_llama7b(self, report):
        bn = report["nodes"]["ampere-a10"]["workloads"]["llama-7b-short"]["kernel_block_n"]
        assert bn == 64

    def test_a10_bert_classifier(self, report):
        bn = report["nodes"]["ampere-a10"]["workloads"]["bert-classifier"]["kernel_block_n"]
        assert bn == 32

    def test_a100_bert_classifier(self, report):
        bn = report["nodes"]["ampere-a100"]["workloads"]["bert-classifier"]["kernel_block_n"]
        assert bn == 64

    def test_h100_bert_classifier(self, report):
        bn = report["nodes"]["hopper-h100"]["workloads"]["bert-classifier"]["kernel_block_n"]
        assert bn == 64

    def test_b200_llama70b(self, report):
        bn = report["nodes"]["blackwell-b200"]["workloads"]["llama-70b-long"]["kernel_block_n"]
        assert bn == 64

    def test_thor_llama70b(self, report):
        bn = report["nodes"]["thor-gh200"]["workloads"]["llama-70b-long"]["kernel_block_n"]
        assert bn == 64


# --- Forward FLOPS ---

class TestFwdFlops:
    def test_llama7b_short(self, report):
        flops = report["nodes"]["ampere-a100"]["workloads"]["llama-7b-short"]["fwd_flops"]
        assert flops == 1099511627776

    def test_llama70b_long(self, report):
        flops = report["nodes"]["ampere-a100"]["workloads"]["llama-70b-long"]["fwd_flops"]
        assert flops == 17592186044416

    def test_bert_classifier(self, report):
        flops = report["nodes"]["ampere-a100"]["workloads"]["bert-classifier"]["fwd_flops"]
        assert flops == 211106232532992

    def test_flops_same_across_nodes(self, report):
        nodes = list(report["nodes"].keys())
        for wl in ["llama-7b-short", "llama-70b-long", "bert-classifier"]:
            values = [report["nodes"][n]["workloads"][wl]["fwd_flops"] for n in nodes]
            assert all(v == values[0] for v in values), \
                f"FLOPS mismatch across nodes for {wl}"


# --- Memory Per Layer ---

class TestMemoryPerLayer:
    def test_llama7b_standard(self, report):
        mem = report["nodes"]["ampere-a100"]["workloads"]["llama-7b-short"]["memory_per_layer"]
        assert mem["standard_bytes"] == 10737418240

    def test_llama7b_flash(self, report):
        mem = report["nodes"]["ampere-a100"]["workloads"]["llama-7b-short"]["memory_per_layer"]
        assert mem["flash_bytes"] == 2155872256

    def test_llama70b_standard(self, report):
        mem = report["nodes"]["hopper-h100"]["workloads"]["llama-70b-long"]["memory_per_layer"]
        assert mem["standard_bytes"] == 141733920768

    def test_llama70b_flash(self, report):
        mem = report["nodes"]["hopper-h100"]["workloads"]["llama-70b-long"]["memory_per_layer"]
        assert mem["flash_bytes"] == 4311744512

    def test_bert_standard(self, report):
        mem = report["nodes"]["blackwell-b200"]["workloads"]["bert-classifier"]["memory_per_layer"]
        assert mem["standard_bytes"] == 927712935936

    def test_bert_flash(self, report):
        mem = report["nodes"]["blackwell-b200"]["workloads"]["bert-classifier"]["memory_per_layer"]
        assert mem["flash_bytes"] == 103481868288

    def test_memory_same_across_nodes(self, report):
        nodes = list(report["nodes"].keys())
        for wl in ["llama-7b-short", "llama-70b-long", "bert-classifier"]:
            std_vals = [report["nodes"][n]["workloads"][wl]["memory_per_layer"]["standard_bytes"]
                        for n in nodes]
            flash_vals = [report["nodes"][n]["workloads"][wl]["memory_per_layer"]["flash_bytes"]
                          for n in nodes]
            assert all(v == std_vals[0] for v in std_vals), \
                f"Standard memory mismatch for {wl}"
            assert all(v == flash_vals[0] for v in flash_vals), \
                f"Flash memory mismatch for {wl}"


# --- Max Batch Flash ---

class TestMaxBatchFlash:
    def test_llama7b_a100(self, report):
        assert report["nodes"]["ampere-a100"]["workloads"]["llama-7b-short"]["max_batch_flash"] == 1275

    def test_llama7b_a10(self, report):
        assert report["nodes"]["ampere-a10"]["workloads"]["llama-7b-short"]["max_batch_flash"] == 382

    def test_llama70b_a100(self, report):
        assert report["nodes"]["ampere-a100"]["workloads"]["llama-70b-long"]["max_batch_flash"] == 79

    def test_llama70b_a10(self, report):
        assert report["nodes"]["ampere-a10"]["workloads"]["llama-70b-long"]["max_batch_flash"] == 23

    def test_llama70b_b200(self, report):
        assert report["nodes"]["blackwell-b200"]["workloads"]["llama-70b-long"]["max_batch_flash"] == 191

    def test_llama70b_thor(self, report):
        assert report["nodes"]["thor-gh200"]["workloads"]["llama-70b-long"]["max_batch_flash"] == 140

    def test_bert_a100(self, report):
        assert report["nodes"]["ampere-a100"]["workloads"]["bert-classifier"]["max_batch_flash"] == 212

    def test_bert_a10(self, report):
        assert report["nodes"]["ampere-a10"]["workloads"]["bert-classifier"]["max_batch_flash"] == 63

    def test_bert_h100(self, report):
        assert report["nodes"]["hopper-h100"]["workloads"]["bert-classifier"]["max_batch_flash"] == 212

    def test_bert_b200(self, report):
        assert report["nodes"]["blackwell-b200"]["workloads"]["bert-classifier"]["max_batch_flash"] == 510

    def test_bert_thor(self, report):
        assert report["nodes"]["thor-gh200"]["workloads"]["bert-classifier"]["max_batch_flash"] == 374


# --- Feasibility ---

class TestFeasibility:
    def test_llama7b_all_feasible(self, report):
        for node in report["nodes"]:
            assert report["nodes"][node]["workloads"]["llama-7b-short"]["feasible"] is True, \
                f"llama-7b-short should be feasible on {node}"

    def test_llama70b_all_feasible(self, report):
        for node in report["nodes"]:
            assert report["nodes"][node]["workloads"]["llama-70b-long"]["feasible"] is True, \
                f"llama-70b-long should be feasible on {node}"

    def test_bert_infeasible_a100(self, report):
        assert report["nodes"]["ampere-a100"]["workloads"]["bert-classifier"]["feasible"] is False

    def test_bert_infeasible_a10(self, report):
        assert report["nodes"]["ampere-a10"]["workloads"]["bert-classifier"]["feasible"] is False

    def test_bert_infeasible_h100(self, report):
        assert report["nodes"]["hopper-h100"]["workloads"]["bert-classifier"]["feasible"] is False

    def test_bert_feasible_b200(self, report):
        assert report["nodes"]["blackwell-b200"]["workloads"]["bert-classifier"]["feasible"] is True

    def test_bert_feasible_thor(self, report):
        assert report["nodes"]["thor-gh200"]["workloads"]["bert-classifier"]["feasible"] is True


# --- Data Parallel GPUs ---

class TestDataParallelGpus:
    def test_llama7b_all_single(self, report):
        for node in report["nodes"]:
            assert report["nodes"][node]["workloads"]["llama-7b-short"]["data_parallel_gpus"] == 1

    def test_llama70b_all_single(self, report):
        for node in report["nodes"]:
            assert report["nodes"][node]["workloads"]["llama-70b-long"]["data_parallel_gpus"] == 1

    def test_bert_a100_parallel(self, report):
        assert report["nodes"]["ampere-a100"]["workloads"]["bert-classifier"]["data_parallel_gpus"] == 2

    def test_bert_a10_parallel(self, report):
        assert report["nodes"]["ampere-a10"]["workloads"]["bert-classifier"]["data_parallel_gpus"] == 5

    def test_bert_h100_parallel(self, report):
        assert report["nodes"]["hopper-h100"]["workloads"]["bert-classifier"]["data_parallel_gpus"] == 2

    def test_bert_b200_single(self, report):
        assert report["nodes"]["blackwell-b200"]["workloads"]["bert-classifier"]["data_parallel_gpus"] == 1

    def test_bert_thor_single(self, report):
        assert report["nodes"]["thor-gh200"]["workloads"]["bert-classifier"]["data_parallel_gpus"] == 1


# --- Price Performance ---

class TestPricePerformance:
    def test_llama7b_a100(self, report):
        pp = report["nodes"]["ampere-a100"]["workloads"]["llama-7b-short"]["price_performance"]
        assert pp == pytest.approx(89.14, abs=0.01)

    def test_llama7b_a10(self, report):
        pp = report["nodes"]["ampere-a10"]["workloads"]["llama-7b-short"]["price_performance"]
        assert pp == pytest.approx(104.17, abs=0.01)

    def test_llama7b_h100(self, report):
        pp = report["nodes"]["hopper-h100"]["workloads"]["llama-7b-short"]["price_performance"]
        assert pp == pytest.approx(116.47, abs=0.01)

    def test_llama7b_b200(self, report):
        pp = report["nodes"]["blackwell-b200"]["workloads"]["llama-7b-short"]["price_performance"]
        assert pp == pytest.approx(100.0, abs=0.01)

    def test_llama7b_thor(self, report):
        pp = report["nodes"]["thor-gh200"]["workloads"]["llama-7b-short"]["price_performance"]
        assert pp == pytest.approx(82.5, abs=0.01)

    def test_bert_a100_parallel(self, report):
        pp = report["nodes"]["ampere-a100"]["workloads"]["bert-classifier"]["price_performance"]
        assert pp == pytest.approx(44.57, abs=0.01)

    def test_bert_a10_parallel(self, report):
        pp = report["nodes"]["ampere-a10"]["workloads"]["bert-classifier"]["price_performance"]
        assert pp == pytest.approx(20.83, abs=0.01)

    def test_bert_h100_parallel(self, report):
        pp = report["nodes"]["hopper-h100"]["workloads"]["bert-classifier"]["price_performance"]
        assert pp == pytest.approx(58.24, abs=0.01)

    def test_bert_b200_single(self, report):
        pp = report["nodes"]["blackwell-b200"]["workloads"]["bert-classifier"]["price_performance"]
        assert pp == pytest.approx(100.0, abs=0.01)

    def test_bert_thor_single(self, report):
        pp = report["nodes"]["thor-gh200"]["workloads"]["bert-classifier"]["price_performance"]
        assert pp == pytest.approx(82.5, abs=0.01)

    def test_pp_same_for_feasible_workloads(self, report):
        """For workloads feasible on all nodes, PP is identical across workloads on each node"""
        for node in report["nodes"]:
            pp_7b = report["nodes"][node]["workloads"]["llama-7b-short"]["price_performance"]
            pp_70b = report["nodes"][node]["workloads"]["llama-70b-long"]["price_performance"]
            assert pp_7b == pytest.approx(pp_70b, abs=0.01)


# --- Performance Analysis ---

class TestPerformanceAnalysis:
    def test_memory_savings_llama7b(self, report):
        ratio = report["performance_analysis"]["llama-7b-short"]["memory_savings_ratio"]
        assert ratio == pytest.approx(5.0, abs=0.05)

    def test_memory_savings_llama70b(self, report):
        ratio = report["performance_analysis"]["llama-70b-long"]["memory_savings_ratio"]
        assert ratio == pytest.approx(32.9, abs=0.05)

    def test_memory_savings_bert(self, report):
        ratio = report["performance_analysis"]["bert-classifier"]["memory_savings_ratio"]
        assert ratio == pytest.approx(9.0, abs=0.05)

    def test_flash_attention_impact_order(self, report):
        expected = ["llama-70b-long", "bert-classifier", "llama-7b-short"]
        assert report["performance_analysis"]["flash_attention_impact"] == expected

    def test_performance_analysis_has_all_workloads(self, report):
        for wl in ["llama-7b-short", "llama-70b-long", "bert-classifier"]:
            assert wl in report["performance_analysis"]
            assert "memory_savings_ratio" in report["performance_analysis"][wl]


# --- Build Priority ---

class TestBuildPriority:
    def test_build_priority_order(self, report):
        expected = [
            "blackwell-b200",
            "hopper-h100",
            "thor-gh200",
            "ampere-a100",
            "ampere-a10",
        ]
        assert report["build_priority"] == expected

    def test_build_priority_length(self, report):
        assert len(report["build_priority"]) == 5

    def test_build_priority_contains_all_nodes(self, report):
        assert set(report["build_priority"]) == set(report["nodes"].keys())


# --- Deployment Plan ---

class TestDeploymentPlan:
    def test_llama7b_assignment(self, report):
        plan = report["deployment_plan"]["llama-7b-short"]
        assert plan["assigned_node"] == "hopper-h100"
        assert plan["gpus_required"] == 1
        assert plan["price_performance"] == pytest.approx(116.47, abs=0.01)

    def test_llama70b_assignment(self, report):
        plan = report["deployment_plan"]["llama-70b-long"]
        assert plan["assigned_node"] == "hopper-h100"
        assert plan["gpus_required"] == 1
        assert plan["price_performance"] == pytest.approx(116.47, abs=0.01)

    def test_bert_assignment(self, report):
        plan = report["deployment_plan"]["bert-classifier"]
        assert plan["assigned_node"] == "blackwell-b200"
        assert plan["gpus_required"] == 1
        assert plan["price_performance"] == pytest.approx(100.0, abs=0.01)

    def test_bert_picks_feasible_over_infeasible(self, report):
        """bert-classifier should be assigned to a feasible node despite higher cost"""
        plan = report["deployment_plan"]["bert-classifier"]
        assigned = plan["assigned_node"]
        node_data = report["nodes"][assigned]["workloads"]["bert-classifier"]
        assert node_data["feasible"] is True

    def test_all_plans_have_required_fields(self, report):
        for wl_name, plan in report["deployment_plan"].items():
            assert "assigned_node" in plan, f"{wl_name} plan missing assigned_node"
            assert "gpus_required" in plan, f"{wl_name} plan missing gpus_required"
            assert "price_performance" in plan, f"{wl_name} plan missing price_performance"


# --- Ranking ---

class TestRanking:
    def test_ranking_order(self, report):
        expected = [
            "blackwell-b200",
            "hopper-h100",
            "thor-gh200",
            "ampere-a10",
            "ampere-a100",
        ]
        assert report["ranking"] == expected

    def test_ranking_length(self, report):
        assert len(report["ranking"]) == 5

    def test_ranking_contains_all_nodes(self, report):
        assert set(report["ranking"]) == set(report["nodes"].keys())
