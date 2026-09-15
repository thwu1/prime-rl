
"""
Tests for MoE Inference Cluster Capacity Analysis.

Validates /app/analysis.json against expected values derived from the
benchmark database and FlashMLA source code.
"""
import json
import math
import os

import pytest


@pytest.fixture(scope="module")
def analysis():
    path = "/app/analysis.json"
    assert os.path.exists(path), f"Output file {path} does not exist"
    with open(path) as f:
        data = json.load(f)
    return {item["workload_id"]: item for item in data}


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_file_exists(self):
        assert os.path.exists("/app/analysis.json")

    def test_is_list(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_four_workloads(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        assert len(data) == 4

    def test_ordered_by_id(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        ids = [item["workload_id"] for item in data]
        assert ids == sorted(ids)

    def test_required_fields(self):
        required = [
            "workload_id", "workload_name", "kv_bytes_per_token",
            "total_kv_memory_gb", "max_batch_size", "fits_in_memory",
            "moe_flops_per_token", "attn_flops_per_token",
            "attn_arithmetic_intensity", "ep_dispatch_volume_mb",
            "min_ep_sms_90pct", "available_compute_sms",
        ]
        with open("/app/analysis.json") as f:
            data = json.load(f)
        for item in data:
            for field in required:
                assert field in item, (
                    f"Missing '{field}' in workload {item.get('workload_id')}"
                )


# ---------------------------------------------------------------------------
# Workload 1: short_ctx_fp8
# deepseek_v32, V32_FP8Sparse, batch=256, seq=4096, fp8_dispatch
# ---------------------------------------------------------------------------

class TestWorkload1:
    WID = 1

    def test_name(self, analysis):
        assert analysis[self.WID]["workload_name"] == "short_ctx_fp8"

    def test_kv_bytes_per_token(self, analysis):
        # V32_FP8Sparse: d_nope(512) + num_tiles(4)*4 + elem_size(2)*d_rope(64) = 656
        assert analysis[self.WID]["kv_bytes_per_token"] == 656

    def test_total_kv_memory_gb(self, analysis):
        expected = 256 * 4096 * 656 * 61 / 1e9
        assert analysis[self.WID]["total_kv_memory_gb"] == pytest.approx(
            expected, rel=1e-6
        )

    def test_max_batch_size(self, analysis):
        # floor((80.0 - 22.0) * 1e9 / (4096 * 656 * 61)) = 353
        assert analysis[self.WID]["max_batch_size"] == 353

    def test_fits_in_memory(self, analysis):
        assert analysis[self.WID]["fits_in_memory"] is True

    def test_moe_flops(self, analysis):
        # topk(8) * 6 * hidden(7168) * ffn(2048) = 704643072
        assert analysis[self.WID]["moe_flops_per_token"] == 704643072

    def test_attn_flops(self, analysis):
        # 2 * heads(128) * seq(4096) * (d_qk(576) + d_v(512)) = 1140850688
        assert analysis[self.WID]["attn_flops_per_token"] == 1140850688

    def test_attn_arithmetic_intensity(self, analysis):
        # 2*128*(576+512) / 656 = 424.6
        assert analysis[self.WID]["attn_arithmetic_intensity"] == pytest.approx(
            424.6, abs=0.05
        )

    def test_ep_dispatch_volume(self, analysis):
        # 256 * 8 * 7168 * 1 / 1e6 = 14.680064
        assert analysis[self.WID]["ep_dispatch_volume_mb"] == pytest.approx(
            14.680064, rel=1e-6
        )

    def test_min_ep_sms(self, analysis):
        # peak=726, 90%=653.4; 32 SMs -> 690 >= 653.4
        assert analysis[self.WID]["min_ep_sms_90pct"] == 32

    def test_available_compute_sms(self, analysis):
        assert analysis[self.WID]["available_compute_sms"] == 100


# ---------------------------------------------------------------------------
# Workload 2: long_ctx_bf16
# deepseek_v32, bf16, batch=128, seq=8192, bf16_dispatch
# ---------------------------------------------------------------------------

class TestWorkload2:
    WID = 2

    def test_name(self, analysis):
        assert analysis[self.WID]["workload_name"] == "long_ctx_bf16"

    def test_kv_bytes_per_token(self, analysis):
        # bf16: (d_nope(512) + d_rope(64)) * 2 = 1152
        assert analysis[self.WID]["kv_bytes_per_token"] == 1152

    def test_total_kv_memory_gb(self, analysis):
        expected = 128 * 8192 * 1152 * 61 / 1e9
        assert analysis[self.WID]["total_kv_memory_gb"] == pytest.approx(
            expected, rel=1e-6
        )

    def test_max_batch_size(self, analysis):
        # floor((80.0 - 22.0) * 1e9 / (8192 * 1152 * 61)) = 100
        assert analysis[self.WID]["max_batch_size"] == 100

    def test_fits_in_memory(self, analysis):
        # 128 > 100 -> does NOT fit
        assert analysis[self.WID]["fits_in_memory"] is False

    def test_moe_flops(self, analysis):
        assert analysis[self.WID]["moe_flops_per_token"] == 704643072

    def test_attn_flops(self, analysis):
        # 2 * 128 * 8192 * 1088 = 2281701376
        assert analysis[self.WID]["attn_flops_per_token"] == 2281701376

    def test_attn_arithmetic_intensity(self, analysis):
        # 2*128*1088 / 1152 = 241.8
        assert analysis[self.WID]["attn_arithmetic_intensity"] == pytest.approx(
            241.8, abs=0.05
        )

    def test_ep_dispatch_volume(self, analysis):
        # 128 * 8 * 7168 * 2 / 1e6 = 14.680064
        assert analysis[self.WID]["ep_dispatch_volume_mb"] == pytest.approx(
            14.680064, rel=1e-6
        )

    def test_min_ep_sms(self, analysis):
        assert analysis[self.WID]["min_ep_sms_90pct"] == 32

    def test_available_compute_sms(self, analysis):
        assert analysis[self.WID]["available_compute_sms"] == 100


# ---------------------------------------------------------------------------
# Workload 3: m1_fp8
# deepseek_m1, MODEL1_FP8Sparse, batch=512, seq=2048, fp8_dispatch
# ---------------------------------------------------------------------------

class TestWorkload3:
    WID = 3

    def test_name(self, analysis):
        assert analysis[self.WID]["workload_name"] == "m1_fp8"

    def test_kv_bytes_per_token(self, analysis):
        # MODEL1_FP8Sparse: d_nope(448) + 2*d_rope(64) + num_tiles(7) + 1 = 584
        assert analysis[self.WID]["kv_bytes_per_token"] == 584

    def test_total_kv_memory_gb(self, analysis):
        expected = 512 * 2048 * 584 * 48 / 1e9
        assert analysis[self.WID]["total_kv_memory_gb"] == pytest.approx(
            expected, rel=1e-6
        )

    def test_max_batch_size(self, analysis):
        # floor((80.0 - 12.0) * 1e9 / (2048 * 584 * 48)) = 1184
        assert analysis[self.WID]["max_batch_size"] == 1184

    def test_fits_in_memory(self, analysis):
        assert analysis[self.WID]["fits_in_memory"] is True

    def test_moe_flops(self, analysis):
        # topk(6) * 6 * hidden(5120) * ffn(1536) = 283115520
        assert analysis[self.WID]["moe_flops_per_token"] == 283115520

    def test_attn_flops(self, analysis):
        # 2 * 64 * 2048 * (512 + 448) = 251658240
        assert analysis[self.WID]["attn_flops_per_token"] == 251658240

    def test_attn_arithmetic_intensity(self, analysis):
        # 2*64*960 / 584 = 210.4
        assert analysis[self.WID]["attn_arithmetic_intensity"] == pytest.approx(
            210.4, abs=0.05
        )

    def test_ep_dispatch_volume(self, analysis):
        # 512 * 6 * 5120 * 1 / 1e6 = 15.72864
        assert analysis[self.WID]["ep_dispatch_volume_mb"] == pytest.approx(
            15.72864, rel=1e-6
        )

    def test_min_ep_sms(self, analysis):
        assert analysis[self.WID]["min_ep_sms_90pct"] == 32

    def test_available_compute_sms(self, analysis):
        assert analysis[self.WID]["available_compute_sms"] == 100


# ---------------------------------------------------------------------------
# Workload 4: ultra_long
# deepseek_v32, V32_FP8Sparse, batch=64, seq=131072, fp8_dispatch
# ---------------------------------------------------------------------------

class TestWorkload4:
    WID = 4

    def test_name(self, analysis):
        assert analysis[self.WID]["workload_name"] == "ultra_long"

    def test_kv_bytes_per_token(self, analysis):
        assert analysis[self.WID]["kv_bytes_per_token"] == 656

    def test_total_kv_memory_gb(self, analysis):
        expected = 64 * 131072 * 656 * 61 / 1e9
        assert analysis[self.WID]["total_kv_memory_gb"] == pytest.approx(
            expected, rel=1e-6
        )

    def test_max_batch_size(self, analysis):
        # floor((80.0 - 22.0) * 1e9 / (131072 * 656 * 61)) = 11
        assert analysis[self.WID]["max_batch_size"] == 11

    def test_fits_in_memory(self, analysis):
        # 64 > 11 -> does NOT fit
        assert analysis[self.WID]["fits_in_memory"] is False

    def test_moe_flops(self, analysis):
        assert analysis[self.WID]["moe_flops_per_token"] == 704643072

    def test_attn_flops(self, analysis):
        # 2 * 128 * 131072 * 1088 = 36507222016
        assert analysis[self.WID]["attn_flops_per_token"] == 36507222016

    def test_attn_arithmetic_intensity(self, analysis):
        # Same model/format as WL1 -> 424.6
        assert analysis[self.WID]["attn_arithmetic_intensity"] == pytest.approx(
            424.6, abs=0.05
        )

    def test_ep_dispatch_volume(self, analysis):
        # 64 * 8 * 7168 * 1 / 1e6 = 3.670016
        assert analysis[self.WID]["ep_dispatch_volume_mb"] == pytest.approx(
            3.670016, rel=1e-6
        )

    def test_min_ep_sms(self, analysis):
        assert analysis[self.WID]["min_ep_sms_90pct"] == 32

    def test_available_compute_sms(self, analysis):
        assert analysis[self.WID]["available_compute_sms"] == 100


# ---------------------------------------------------------------------------
# Cross-workload consistency tests
# ---------------------------------------------------------------------------

class TestCrossWorkload:
    def test_same_model_same_format_same_kv_bytes(self, analysis):
        """WL1 and WL4 use same model+format -> same kv_bytes_per_token."""
        assert analysis[1]["kv_bytes_per_token"] == analysis[4]["kv_bytes_per_token"]

    def test_bf16_larger_than_fp8(self, analysis):
        """BF16 format should use more bytes per token than FP8 for the same model."""
        assert analysis[2]["kv_bytes_per_token"] > analysis[1]["kv_bytes_per_token"]

    def test_longer_seq_lower_max_batch(self, analysis):
        """Longer sequences require more KV memory -> lower max batch."""
        assert analysis[4]["max_batch_size"] < analysis[1]["max_batch_size"]

    def test_all_ep_sms_consistent(self, analysis):
        """All workloads use the same GPU -> same min_ep_sms_90pct."""
        sms_values = [analysis[i]["min_ep_sms_90pct"] for i in [1, 2, 3, 4]]
        assert len(set(sms_values)) == 1

    def test_available_sms_plus_ep_sms_equals_total(self, analysis):
        """available_compute_sms + min_ep_sms_90pct = gpu sm_count (132)."""
        for wid in [1, 2, 3, 4]:
            total = (analysis[wid]["available_compute_sms"]
                     + analysis[wid]["min_ep_sms_90pct"])
            assert total == 132

    def test_fits_matches_batch_vs_max(self, analysis):
        """fits_in_memory must be consistent with batch_size vs max_batch_size."""
        batch_sizes = {1: 256, 2: 128, 3: 512, 4: 64}
        for wid in [1, 2, 3, 4]:
            fits = analysis[wid]["fits_in_memory"]
            max_b = analysis[wid]["max_batch_size"]
            expected_fits = batch_sizes[wid] <= max_b
            assert fits == expected_fits, (
                f"WL{wid}: fits={fits} but batch={batch_sizes[wid]}, max={max_b}"
            )
