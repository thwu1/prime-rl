"""Tests for the ONNX Quantization Pipeline.

Verifies BN fusion, Q/DQ insertion, scale computation, model validity,
diagnostic report, and correct quantization approach.
"""

import json
import os
import subprocess

import numpy as np
import onnx
import onnxruntime as ort
import pytest
from onnx import TensorProto, helper, numpy_helper



@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Run the quantization pipeline once before all tests."""
    pipeline_path = "/app/quant_pipeline.py"
    assert os.path.exists(pipeline_path), \
        "quant_pipeline.py not found at /app/quant_pipeline.py"
    assert os.path.exists("/app/model.onnx"), \
        "model.onnx not found — run generate_model.py first"
    assert os.path.exists("/app/calibration_data.npy"), \
        "calibration_data.npy not found — run generate_calibration.py first"

    result = subprocess.run([
        "python3", pipeline_path,
        "--input", "/app/model.onnx",
        "--calibration", "/app/calibration_data.npy",
        "--config", "/app/config.json",
        "--output-fused", "/app/model_fused.onnx",
        "--output-quantized", "/app/model_quantized.onnx",
        "--report", "/app/quantization_report.json"
    ], capture_output=True, text=True, cwd="/app", timeout=180)

    assert result.returncode == 0, \
        f"Pipeline failed (exit {result.returncode}):\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    assert os.path.exists("/app/model_fused.onnx"), "Fused model not created"
    assert os.path.exists("/app/model_quantized.onnx"), "Quantized model not created"
    assert os.path.exists("/app/quantization_report.json"), "Report not created"


# ===========================================================================
# BN Fusion Tests
# ===========================================================================

class TestBNFusion:
    def test_no_bn_nodes(self):
        """Fused model must have zero BatchNormalization nodes."""
        model = onnx.load("/app/model_fused.onnx")
        bn_count = sum(1 for n in model.graph.node
                       if n.op_type == "BatchNormalization")
        assert bn_count == 0, f"Expected 0 BN nodes, got {bn_count}"

    def test_conv_count_preserved(self):
        """All 3 Conv nodes must be preserved after fusion."""
        model = onnx.load("/app/model_fused.onnx")
        conv_count = sum(1 for n in model.graph.node if n.op_type == "Conv")
        assert conv_count == 3, f"Expected 3 Conv nodes, got {conv_count}"

    def test_all_convs_have_bias(self):
        """After fusion, every Conv must have a bias input."""
        model = onnx.load("/app/model_fused.onnx")
        for node in model.graph.node:
            if node.op_type == "Conv":
                assert len(node.input) >= 3, \
                    f"Conv '{node.name}' has only {len(node.input)} inputs; needs bias"
                bias_name = node.input[2]
                assert bias_name != "", \
                    f"Conv '{node.name}' bias input name is empty"

    def test_fused_model_valid(self):
        """Fused model must pass onnx.checker."""
        model = onnx.load("/app/model_fused.onnx")
        onnx.checker.check_model(model)

    def test_fused_equivalence(self):
        """Fused model must produce the same output as the original."""
        orig_sess = ort.InferenceSession("/app/model.onnx")
        fused_sess = ort.InferenceSession("/app/model_fused.onnx")
        np.random.seed(999)
        x = np.random.randn(1, 3, 32, 32).astype(np.float32)
        orig_out = orig_sess.run(None, {"input": x})[0]
        fused_out = fused_sess.run(None, {"input": x})[0]
        np.testing.assert_allclose(orig_out, fused_out, rtol=1e-5, atol=1e-5)

    def test_fused_equivalence_multiple_inputs(self):
        """Fused equivalence must hold across several random inputs."""
        orig_sess = ort.InferenceSession("/app/model.onnx")
        fused_sess = ort.InferenceSession("/app/model_fused.onnx")
        for seed in [42, 123, 456, 789, 1337]:
            np.random.seed(seed)
            x = np.random.randn(1, 3, 32, 32).astype(np.float32)
            orig_out = orig_sess.run(None, {"input": x})[0]
            fused_out = fused_sess.run(None, {"input": x})[0]
            np.testing.assert_allclose(
                orig_out, fused_out, rtol=1e-5, atol=1e-5,
                err_msg=f"Mismatch for seed {seed}")

    def test_no_unreferenced_initializers(self):
        """Fused model must not have initializers unreferenced by any node."""
        model = onnx.load("/app/model_fused.onnx")
        referenced = set()
        for node in model.graph.node:
            for inp in node.input:
                if inp:
                    referenced.add(inp)
        init_names = {i.name for i in model.graph.initializer}
        unreferenced = init_names - referenced
        assert len(unreferenced) == 0, \
            f"Unreferenced initializers in fused model: {unreferenced}"


# ===========================================================================
# Quantized Model Structure Tests
# ===========================================================================

class TestQuantizedModelStructure:
    def test_has_quantize_nodes(self):
        """Must have at least 6 QuantizeLinear nodes (3 weight + 3 activation)."""
        model = onnx.load("/app/model_quantized.onnx")
        q_count = sum(1 for n in model.graph.node
                      if n.op_type == "QuantizeLinear")
        assert q_count >= 6, f"Expected >= 6 QuantizeLinear, got {q_count}"

    def test_has_dequantize_nodes(self):
        """Must have at least 6 DequantizeLinear nodes."""
        model = onnx.load("/app/model_quantized.onnx")
        dq_count = sum(1 for n in model.graph.node
                       if n.op_type == "DequantizeLinear")
        assert dq_count >= 6, f"Expected >= 6 DequantizeLinear, got {dq_count}"

    def test_quantized_model_valid(self):
        """Quantized model must pass onnx.checker."""
        model = onnx.load("/app/model_quantized.onnx")
        onnx.checker.check_model(model)

    def test_inference_output_shape(self):
        """Quantized model must produce output shape [1, 10]."""
        sess = ort.InferenceSession("/app/model_quantized.onnx")
        np.random.seed(999)
        x = np.random.randn(1, 3, 32, 32).astype(np.float32)
        output = sess.run(None, {"input": x})[0]
        assert output.shape == (1, 10), \
            f"Expected shape (1, 10), got {output.shape}"
        assert np.all(np.isfinite(output)), "Output contains non-finite values"

    def test_quantized_accuracy(self):
        """Quantized output must be within bounded error of fused output."""
        fused_sess = ort.InferenceSession("/app/model_fused.onnx")
        quant_sess = ort.InferenceSession("/app/model_quantized.onnx")

        for seed in [999, 42, 7]:
            np.random.seed(seed)
            x = np.random.randn(1, 3, 32, 32).astype(np.float32)
            fused_out = fused_sess.run(None, {"input": x})[0]
            quant_out = quant_sess.run(None, {"input": x})[0]
            max_diff = np.max(np.abs(fused_out - quant_out))
            fused_range = np.max(np.abs(fused_out)) + 1e-10
            relative_error = max_diff / fused_range
            assert relative_error < 1.0, \
                f"Quantization error too large (rel={relative_error:.4f}, seed={seed})"


# ===========================================================================
# Q/DQ Pattern Tests
# ===========================================================================

class TestQDQPattern:
    def _get_node_by_output(self, model, output_name, op_type):
        """Find a node of given op_type that produces output_name."""
        for n in model.graph.node:
            if n.op_type == op_type and output_name in n.output:
                return n
        return None

    def test_weight_qdq_chain(self):
        """Each Conv weight must go through QuantizeLinear -> DequantizeLinear."""
        model = onnx.load("/app/model_quantized.onnx")
        conv_nodes = [n for n in model.graph.node if n.op_type == "Conv"]
        assert len(conv_nodes) == 3

        for conv in conv_nodes:
            weight_input = conv.input[1]
            dq = self._get_node_by_output(model, weight_input, "DequantizeLinear")
            assert dq is not None, \
                f"Conv '{conv.name}' weight not fed by DequantizeLinear"

            q_output = dq.input[0]
            q = self._get_node_by_output(model, q_output, "QuantizeLinear")
            assert q is not None, \
                f"DQ feeding Conv '{conv.name}' weight not fed by QuantizeLinear"

            # Q's input should be an initializer (the original weight)
            orig_weight_name = q.input[0]
            has_init = any(i.name == orig_weight_name
                          for i in model.graph.initializer)
            assert has_init, \
                f"QuantizeLinear input '{orig_weight_name}' is not an initializer"

    def test_activation_qdq_chain(self):
        """Each Conv activation input must go through Q -> DQ."""
        model = onnx.load("/app/model_quantized.onnx")
        conv_nodes = [n for n in model.graph.node if n.op_type == "Conv"]

        for conv in conv_nodes:
            act_input = conv.input[0]
            dq = self._get_node_by_output(model, act_input, "DequantizeLinear")
            assert dq is not None, \
                f"Conv '{conv.name}' activation not fed by DequantizeLinear"

            q_output = dq.input[0]
            q = self._get_node_by_output(model, q_output, "QuantizeLinear")
            assert q is not None, \
                f"DQ feeding Conv '{conv.name}' activation not fed by QuantizeLinear"

    def test_per_channel_weight_scales(self):
        """Weight scales must be 1-D float32 with length = output channels."""
        model = onnx.load("/app/model_quantized.onnx")

        for conv in (n for n in model.graph.node if n.op_type == "Conv"):
            weight_input = conv.input[1]
            dq = self._get_node_by_output(model, weight_input, "DequantizeLinear")
            q_output = dq.input[0]
            q = self._get_node_by_output(model, q_output, "QuantizeLinear")

            # Expected channel count from weight initializer
            weight_name = q.input[0]
            weight_init = next(i for i in model.graph.initializer
                               if i.name == weight_name)
            expected_channels = weight_init.dims[0]

            # Check scale tensor
            scale_name = q.input[1]
            scale_init = next(i for i in model.graph.initializer
                              if i.name == scale_name)
            scale = numpy_helper.to_array(scale_init)

            assert scale.ndim == 1, \
                f"Weight scale ndim should be 1, got {scale.ndim}"
            assert scale.shape[0] == expected_channels, \
                f"Weight scale dim {scale.shape[0]} != channels {expected_channels}"
            assert np.all(scale > 0), "Weight scales must be positive"
            assert scale.dtype == np.float32, \
                f"Weight scale dtype should be float32, got {scale.dtype}"

    def test_per_tensor_activation_scales(self):
        """Activation scales must be scalar (0-D or shape [1]) and positive."""
        model = onnx.load("/app/model_quantized.onnx")

        for conv in (n for n in model.graph.node if n.op_type == "Conv"):
            act_input = conv.input[0]
            dq = self._get_node_by_output(model, act_input, "DequantizeLinear")
            q_output = dq.input[0]
            q = self._get_node_by_output(model, q_output, "QuantizeLinear")

            scale_name = q.input[1]
            scale_init = next(i for i in model.graph.initializer
                              if i.name == scale_name)
            scale = numpy_helper.to_array(scale_init)

            assert scale.size == 1, \
                f"Activation scale should be scalar, got shape {scale.shape}"
            assert float(scale.flat[0]) > 0, "Activation scale must be positive"

    def test_input_activation_scale_value(self):
        """Activation scale for graph input must reflect calibration data range."""
        cal = np.load("/app/calibration_data.npy")
        expected = float(np.max(np.abs(cal))) / 127.0

        model = onnx.load("/app/model_quantized.onnx")
        graph_input_name = model.graph.input[0].name

        # Find QuantizeLinear that directly consumes the graph input
        q_node = None
        for n in model.graph.node:
            if n.op_type == "QuantizeLinear" and n.input[0] == graph_input_name:
                q_node = n
                break
        assert q_node is not None, \
            "No QuantizeLinear found consuming graph input"

        scale_init = next(i for i in model.graph.initializer
                          if i.name == q_node.input[1])
        actual = float(numpy_helper.to_array(scale_init))

        np.testing.assert_allclose(actual, expected, rtol=1e-5,
            err_msg=f"Input activation scale {actual} != expected {expected}")


# ===========================================================================
# Correct Quantization Approach Tests
# ===========================================================================

class TestCorrectApproach:
    def _get_node_by_output(self, model, output_name, op_type):
        for n in model.graph.node:
            if n.op_type == op_type and output_name in n.output:
                return n
        return None

    def test_weight_scale_formula(self):
        """Weight scales must equal max(|W_channel|) / 127 per channel."""
        model = onnx.load("/app/model_quantized.onnx")

        for conv in (n for n in model.graph.node if n.op_type == "Conv"):
            weight_input = conv.input[1]
            dq = self._get_node_by_output(model, weight_input, "DequantizeLinear")
            q_output = dq.input[0]
            q = self._get_node_by_output(model, q_output, "QuantizeLinear")

            weight = numpy_helper.to_array(
                next(i for i in model.graph.initializer if i.name == q.input[0]))
            scale = numpy_helper.to_array(
                next(i for i in model.graph.initializer if i.name == q.input[1]))

            for c in range(weight.shape[0]):
                ch_max = np.max(np.abs(weight[c]))
                expected = ch_max / 127.0 if ch_max > 0 else 1.0
                np.testing.assert_allclose(
                    scale[c], expected, rtol=1e-5,
                    err_msg=f"Scale mismatch at channel {c} of Conv '{conv.name}'")

    def test_zero_points_are_zero(self):
        """All zero-points must be int8(0) for symmetric quantization."""
        model = onnx.load("/app/model_quantized.onnx")

        for q_node in (n for n in model.graph.node
                       if n.op_type == "QuantizeLinear"):
            if len(q_node.input) >= 3:
                zp_name = q_node.input[2]
                zp_init = next((i for i in model.graph.initializer
                                if i.name == zp_name), None)
                if zp_init is not None:
                    zp = numpy_helper.to_array(zp_init)
                    assert np.all(zp == 0), \
                        f"Zero-point '{zp_name}' is not all-zero: {zp}"

    def test_fake_quant_weight_roundtrip_idempotent(self):
        """DQ(Q(w)) must be idempotent: Q(DQ(Q(w))) == Q(w).

        Fake-quantized values lie on the quantization grid, so
        re-quantizing them must produce identical integer values.
        """
        model = onnx.load("/app/model_quantized.onnx")

        for conv in (n for n in model.graph.node if n.op_type == "Conv"):
            weight_input = conv.input[1]
            dq = self._get_node_by_output(model, weight_input, "DequantizeLinear")
            q_output = dq.input[0]
            q = self._get_node_by_output(model, q_output, "QuantizeLinear")

            weight = numpy_helper.to_array(
                next(i for i in model.graph.initializer if i.name == q.input[0]))
            scale = numpy_helper.to_array(
                next(i for i in model.graph.initializer if i.name == q.input[1]))

            s = scale.reshape([-1] + [1] * (weight.ndim - 1))

            # First round: quantize then dequantize
            q1 = np.clip(np.round(weight / s), -128, 127).astype(np.int8)
            dq1 = q1.astype(np.float32) * s

            # Second round: re-quantize the dequantized values
            q2 = np.clip(np.round(dq1 / s), -128, 127).astype(np.int8)

            np.testing.assert_array_equal(
                q1, q2,
                err_msg=f"Fake-quant round-trip not idempotent for Conv '{conv.name}'")


# ===========================================================================
# Diagnostic Report Tests
# ===========================================================================

class TestDiagnosticReport:
    @pytest.fixture(scope="class")
    def report(self):
        with open("/app/quantization_report.json") as f:
            return json.load(f)

    def test_report_has_required_keys(self, report):
        """Report must contain all required top-level keys."""
        required = {"original_op_counts", "fused_op_counts",
                     "num_quantized_weights", "num_quantized_activations",
                     "weight_scale_ranges", "activation_scales"}
        missing = required - set(report.keys())
        assert len(missing) == 0, f"Report missing keys: {missing}"

    def test_original_op_counts(self, report):
        """Original model op counts must match the generated model."""
        counts = report["original_op_counts"]
        assert counts.get("Conv") == 3, \
            f"Expected 3 Conv in original, got {counts.get('Conv')}"
        assert counts.get("BatchNormalization") == 2, \
            f"Expected 2 BN in original, got {counts.get('BatchNormalization')}"
        assert counts.get("Relu") == 2, \
            f"Expected 2 Relu in original, got {counts.get('Relu')}"

    def test_fused_op_counts(self, report):
        """Fused model must show zero BN and preserved Conv count."""
        counts = report["fused_op_counts"]
        assert counts.get("Conv") == 3, \
            f"Expected 3 Conv in fused, got {counts.get('Conv')}"
        assert counts.get("BatchNormalization", 0) == 0, \
            f"Expected 0 BN in fused, got {counts.get('BatchNormalization')}"

    def test_quantized_counts(self, report):
        """Quantized weight and activation counts must be 3 each."""
        assert report["num_quantized_weights"] == 3, \
            f"Expected 3 quantized weights, got {report['num_quantized_weights']}"
        assert report["num_quantized_activations"] == 3, \
            f"Expected 3 quantized activations, got {report['num_quantized_activations']}"

    def test_weight_scale_ranges_structure(self, report):
        """Weight scale ranges must have 3 entries with valid min/max."""
        ranges = report["weight_scale_ranges"]
        assert len(ranges) == 3, \
            f"Expected 3 weight scale range entries, got {len(ranges)}"
        for name, r in ranges.items():
            assert isinstance(r, dict), f"Range for '{name}' is not a dict"
            assert "min" in r and "max" in r, \
                f"Range for '{name}' missing min/max"
            assert isinstance(r["min"], (int, float)) and r["min"] > 0, \
                f"Invalid min scale for '{name}': {r['min']}"
            assert isinstance(r["max"], (int, float)) and r["max"] > 0, \
                f"Invalid max scale for '{name}': {r['max']}"
            assert r["max"] >= r["min"], \
                f"max < min for '{name}': {r['max']} < {r['min']}"

    def test_activation_scales_structure(self, report):
        """Activation scales must have 3 entries with positive values."""
        scales = report["activation_scales"]
        assert len(scales) == 3, \
            f"Expected 3 activation scale entries, got {len(scales)}"
        for name, s in scales.items():
            assert isinstance(s, (int, float)) and s > 0, \
                f"Invalid activation scale for '{name}': {s}"

    def test_activation_scales_match_model(self, report):
        """Reported activation scales must match scales in the quantized model."""
        model = onnx.load("/app/model_quantized.onnx")
        reported = report["activation_scales"]

        # Collect all activation Q node scales from the quantized model
        model_scales = {}
        for node in model.graph.node:
            if node.op_type == "Conv":
                act_input = node.input[0]
                # Trace back through DQ -> Q
                dq = next((n for n in model.graph.node
                           if n.op_type == "DequantizeLinear"
                           and act_input in n.output), None)
                if dq is None:
                    continue
                q = next((n for n in model.graph.node
                          if n.op_type == "QuantizeLinear"
                          and dq.input[0] in n.output), None)
                if q is None:
                    continue
                scale_init = next((i for i in model.graph.initializer
                                   if i.name == q.input[1]), None)
                if scale_init is not None:
                    tensor_name = q.input[0]
                    model_scales[tensor_name] = float(
                        numpy_helper.to_array(scale_init))

        # Every reported scale must match a model scale
        reported_values = sorted(reported.values())
        model_values = sorted(model_scales.values())
        assert len(reported_values) == len(model_values), \
            f"Scale count mismatch: report={len(reported_values)}, model={len(model_values)}"
        for rv, mv in zip(reported_values, model_values):
            np.testing.assert_allclose(rv, mv, rtol=1e-5,
                err_msg="Reported activation scale doesn't match model scale")
