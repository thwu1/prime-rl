"""
Tests for mixed-storage quantized model forensics task.

"""
import pytest
import numpy as np
import subprocess
import os
import struct
import sqlite3
import tempfile


def run_inference(input_path, output_path):
    """Run the agent's inference.py as a subprocess."""
    result = subprocess.run(
        ["python3", "/app/inference.py", "/app/model", input_path, output_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "inference.py failed with exit code %d\n"
        "stdout: %s\nstderr: %s" % (
            result.returncode, result.stdout, result.stderr))
    assert os.path.exists(output_path), "Output file not created: %s" % output_path
    return np.load(output_path)


def _unpack_m0(packed, nr, nc):
    """Unpack packing_mode 0 (interleaved)."""
    packed = packed.reshape(nr, nc // 8).astype(np.uint64)
    q = np.zeros((nr, nc), dtype=np.int32)
    for j in range(4):
        q[:, (2 * j)::8] = (packed >> (j * 4)) & 0xF
        q[:, (2 * j + 1)::8] = (packed >> (16 + j * 4)) & 0xF
    return q


def _unpack_m1(packed, nr, nc):
    """Unpack packing_mode 1 (sequential)."""
    packed = packed.reshape(nr, nc // 8).astype(np.uint64)
    q = np.zeros((nr, nc), dtype=np.int32)
    for j in range(8):
        q[:, j::8] = (packed >> (j * 4)) & 0xF
    return q


def _unpack_m2(packed, nr, nc):
    """Unpack packing_mode 2 (bitplane)."""
    packed = packed.reshape(nr, nc // 8).astype(np.uint64)
    q = np.zeros((nr, nc), dtype=np.int32)
    for b in range(4):
        for v in range(8):
            q[:, v::8] |= (((packed >> (b * 8 + v)) & 1) << b).astype(
                np.int32)
    return q


_UNPACKERS = {0: _unpack_m0, 1: _unpack_m1, 2: _unpack_m2}


def _gelu_approx(x):
    """GELU with tanh approximation."""
    x64 = x.astype(np.float64)
    result = 0.5 * x64 * (1.0 + np.tanh(
        np.sqrt(2.0 / np.pi) * (x64 + 0.044715 * x64 ** 3)))
    return result.astype(np.float32)


_ACTIVATIONS = {
    "relu": lambda x: np.maximum(x, np.float32(0.0)),
    "gelu": _gelu_approx,
    "none": lambda x: x,
}


def _extract_elf_weights(elf_path):
    """Extract weight data from ELF object file."""
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        subprocess.run(
            ['objcopy', '--dump-section',
             '.quantized_weights=%s' % tmp_path, elf_path],
            check=True, capture_output=True
        )
        with open(tmp_path, 'rb') as f:
            return f.read()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _ref_load(model_dir):
    """Load model using reference implementation with DB and ELF support."""
    db_path = os.path.join(model_dir, 'calibration.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    layer_configs = []
    for row in c.execute("SELECT * FROM layer_config ORDER BY layer_id"):
        layer_configs.append({
            'layer_id': row[0], 'in_features': row[1],
            'out_features': row[2], 'group_size': row[3],
            'packing_mode': row[4], 'scale_dtype': row[5],
            'weight_container': row[6], 'activation': row[7],
            'notes': row[8],
        })

    # Load scale corrections
    corrections = {}
    for row in c.execute(
            "SELECT layer_id, group_idx, row_idx, corrected_scale "
            "FROM scale_corrections"):
        key = (row[0], row[1])
        if key not in corrections:
            corrections[key] = {}
        corrections[key][row[2]] = row[3]

    conn.close()

    layers = []
    activations = []

    for lc in layer_configs:
        li = lc['layer_id']
        nr = lc['out_features']
        nc = lc['in_features']
        gs = lc['group_size']
        ng = nc // gs
        pm = lc['packing_mode']
        sd = lc['scale_dtype']

        # Load weight data from appropriate container
        if lc['weight_container'] == 'elf':
            elf_path = os.path.join(model_dir, 'layer_%d.o' % li)
            raw_data = _extract_elf_weights(elf_path)
            struct.unpack('<III', raw_data[:12])
            raw = np.frombuffer(raw_data[12:], dtype=np.uint32).copy()
        else:
            with open(os.path.join(
                    model_dir, 'layer_%d.qweight' % li), 'rb') as f:
                struct.unpack('<III', f.read(12))
                raw = np.frombuffer(f.read(), dtype=np.uint32).copy()

        q = _UNPACKERS[pm](raw, nr, nc)

        # Load scales
        with open(os.path.join(
                model_dir, 'layer_%d.scales' % li), 'rb') as f:
            struct.unpack('<II', f.read(8))
            if sd == 'float16':
                scales = np.frombuffer(
                    f.read(), dtype=np.float16
                ).copy().astype(np.float32).reshape(nr, ng)
            else:
                scales = np.frombuffer(
                    f.read(), dtype=np.float32
                ).copy().reshape(nr, ng)

        # Apply scale corrections from database
        for (cl, cg), row_corrections in corrections.items():
            if cl == li:
                for row_idx, corrected in row_corrections.items():
                    scales[row_idx, cg] = corrected

        # Load zero-points (always sequential packing)
        with open(os.path.join(
                model_dir, 'layer_%d.zeros' % li), 'rb') as f:
            struct.unpack('<II', f.read(8))
            zppr = (ng + 7) // 8
            zraw = np.frombuffer(f.read(), dtype=np.uint32).copy()
        zp = zraw.reshape(nr, zppr).astype(np.uint64)
        zeros_arr = np.zeros((nr, ng), dtype=np.int32)
        for j in range(ng):
            zeros_arr[:, j] = (zp[:, j // 8] >> ((j % 8) * 4)) & 0xF

        # Dequantize
        se = np.repeat(scales, gs, axis=1)
        ze = np.repeat(zeros_arr, gs, axis=1)
        W = se * (q.astype(np.float32) - ze.astype(np.float32))
        layers.append(W)
        activations.append(lc['activation'])

    return layers, activations


def _ref_forward(layers, activations, x):
    """Reference forward pass."""
    cur = x.astype(np.float32)
    for i, W in enumerate(layers):
        cur = cur @ W.T
        act_fn = _ACTIVATIONS[activations[i]]
        cur = act_fn(cur)
    return cur


@pytest.fixture(scope="session")
def ref_model():
    """Load reference model once per test session."""
    return _ref_load("/app/model")


class TestPrecomputedOutputs:
    """Test against pre-computed reference outputs."""

    @pytest.mark.parametrize("idx", range(5))
    def test_reference_pair(self, idx, tmp_path):
        input_path = "/app/reference/input_%d.npy" % idx
        expected_path = "/app/reference/output_%d.npy" % idx
        output_path = str(tmp_path / ("output_%d.npy" % idx))

        assert os.path.exists(input_path), "Missing: %s" % input_path
        assert os.path.exists(expected_path), "Missing: %s" % expected_path

        output = run_inference(input_path, output_path)
        expected = np.load(expected_path)

        assert output.shape == expected.shape, (
            "Shape mismatch: got %s, expected %s" % (
                output.shape, expected.shape))
        np.testing.assert_allclose(
            output.astype(np.float32),
            expected.astype(np.float32),
            atol=5e-4,
            rtol=1e-3,
            err_msg="Output mismatch for reference pair %d" % idx,
        )


class TestFreshInputs:
    """Test with dynamically generated inputs to prevent hardcoding."""

    def test_fresh_inference_1(self, tmp_path, ref_model):
        layers, activations = ref_model
        rng = np.random.RandomState(77777)
        x = (rng.randn(1, 128) * 0.5).astype(np.float32)
        expected = _ref_forward(layers, activations, x)

        inp = str(tmp_path / "fresh1.npy")
        out = str(tmp_path / "fresh1_out.npy")
        np.save(inp, x)

        output = run_inference(inp, out)
        assert output.shape == expected.shape
        np.testing.assert_allclose(
            output.astype(np.float32),
            expected.astype(np.float32),
            atol=5e-4,
            rtol=1e-3,
            err_msg="Mismatch on fresh input 1",
        )

    def test_fresh_inference_2(self, tmp_path, ref_model):
        layers, activations = ref_model
        rng = np.random.RandomState(31415)
        x = (rng.randn(1, 128) * 0.3).astype(np.float32)
        expected = _ref_forward(layers, activations, x)

        inp = str(tmp_path / "fresh2.npy")
        out = str(tmp_path / "fresh2_out.npy")
        np.save(inp, x)

        output = run_inference(inp, out)
        np.testing.assert_allclose(
            output.astype(np.float32),
            expected.astype(np.float32),
            atol=5e-4,
            rtol=1e-3,
            err_msg="Mismatch on fresh input 2",
        )


class TestOutputProperties:
    """Verify basic output properties."""

    def test_shape_finiteness_variance(self, tmp_path):
        rng = np.random.RandomState(99999)
        x = (rng.randn(1, 128) * 0.5).astype(np.float32)
        inp = str(tmp_path / "prop.npy")
        out = str(tmp_path / "prop_out.npy")
        np.save(inp, x)

        output = run_inference(inp, out)

        assert output.shape == (1, 64), (
            "Expected (1,64), got %s" % (output.shape,))
        assert np.isfinite(output).all(), "Output contains NaN or Inf"
        assert not np.allclose(output, 0), "Output is all zeros"
        assert output.std() > 1e-6, "Output has no variance"
