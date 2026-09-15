
import json
import numpy as np
import pytest
import subprocess
import sys
import tempfile
import os

sys.path.insert(0, '/app')
from ple.encoder import compute_bins, PiecewiseLinearEncoder


class TestComputeBinsQuantile:
    def test_basic(self):
        X = np.arange(10).reshape(-1, 1).astype(np.float64)
        bins = compute_bins(X, n_bins=4)
        assert len(bins) == 1
        # quantiles at [0, 0.25, 0.5, 0.75, 1.0] of [0..9]
        # = [0.0, 2.25, 4.5, 6.75, 9.0], all unique
        np.testing.assert_allclose(bins[0], [0.0, 2.25, 4.5, 6.75, 9.0])

    def test_deduplication(self):
        X = np.array([[0], [0], [0], [0], [0], [1], [2], [3], [4], [5]],
                      dtype=np.float64)
        bins = compute_bins(X, n_bins=4)
        assert len(bins) == 1
        # Many duplicate zeros cause quantile deduplication
        assert len(bins[0]) < 5  # fewer than n_bins+1 edges
        assert len(bins[0]) >= 2  # but at least 2 edges

    def test_multifeature(self):
        X = np.column_stack([
            np.arange(10).astype(np.float64),
            np.arange(10, 20).astype(np.float64),
        ])
        bins = compute_bins(X, n_bins=4)
        assert len(bins) == 2
        np.testing.assert_allclose(bins[0], [0.0, 2.25, 4.5, 6.75, 9.0])
        np.testing.assert_allclose(bins[1], [10.0, 12.25, 14.5, 16.75, 19.0])


class TestComputeBinsTree:
    def test_basic(self):
        X = np.linspace(0, 10, 100).reshape(-1, 1)
        y = (X[:, 0] > 5).astype(np.float64)
        bins = compute_bins(X, n_bins=4, y=y, regression=True,
                           tree_kwargs={'min_samples_leaf': 5})
        assert len(bins) == 1
        b = bins[0]
        assert len(b) >= 2
        # Must include min (0.0) and max (10.0)
        assert np.isclose(b[0], 0.0, atol=0.11)
        assert np.isclose(b[-1], 10.0, atol=0.11)
        # Should find a split near the step at x=5
        interior = b[1:-1]
        has_split_near_5 = any(4.0 < float(e) < 6.0 for e in interior)
        assert has_split_near_5, f"Expected split near 5.0, got edges: {b}"

    def test_classification_tree(self):
        X = np.linspace(0, 10, 100).reshape(-1, 1)
        y = (X[:, 0] > 5).astype(int)
        bins = compute_bins(X, n_bins=4, y=y, regression=False,
                           tree_kwargs={'min_samples_leaf': 5})
        assert len(bins) == 1
        b = bins[0]
        assert len(b) >= 2
        interior = b[1:-1]
        has_split_near_5 = any(4.0 < float(e) < 6.0 for e in interior)
        assert has_split_near_5


class TestComputeBinsValidation:
    def test_nonfinite(self):
        with pytest.raises(ValueError):
            compute_bins(np.array([[np.nan, 1.0], [2.0, 3.0]]), n_bins=2)
        with pytest.raises(ValueError):
            compute_bins(np.array([[np.inf], [1.0], [2.0]]), n_bins=2)

    def test_too_few_rows(self):
        with pytest.raises(ValueError):
            compute_bins(np.array([[1.0, 2.0]]), n_bins=2)

    def test_constant_column(self):
        with pytest.raises(ValueError):
            compute_bins(np.array([[1.0, 2.0], [1.0, 3.0], [1.0, 4.0]]),
                         n_bins=2)

    def test_nbins_bounds(self):
        X = np.arange(5).reshape(-1, 1).astype(np.float64)
        with pytest.raises(ValueError):
            compute_bins(X, n_bins=1)
        with pytest.raises(ValueError):
            compute_bins(X, n_bins=5)

    def test_tree_kwargs_consistency(self):
        X = np.arange(10).reshape(-1, 1).astype(np.float64)
        # tree_kwargs but no y
        with pytest.raises(ValueError):
            compute_bins(X, n_bins=4, tree_kwargs={'min_samples_leaf': 2})
        # tree_kwargs but no regression
        with pytest.raises(ValueError):
            compute_bins(X, n_bins=4, y=np.arange(10, dtype=np.float64),
                         tree_kwargs={'min_samples_leaf': 2})
        # max_leaf_nodes in tree_kwargs
        with pytest.raises(ValueError):
            compute_bins(X, n_bins=4, y=np.arange(10, dtype=np.float64),
                         regression=True,
                         tree_kwargs={'max_leaf_nodes': 5})
        # y provided but tree_kwargs is None
        with pytest.raises(ValueError):
            compute_bins(X, n_bins=4, y=np.arange(10, dtype=np.float64))


class TestEncoderBasic:
    def test_simple_encoding(self):
        """Single feature, 3 bins, value in the middle bin."""
        bins = [np.array([0.0, 1.0, 2.0, 3.0])]
        enc = PiecewiseLinearEncoder(bins)
        X = np.array([[1.5]])
        result = enc.encode_structured(X)
        assert result.shape == (1, 1, 3)
        np.testing.assert_allclose(result[0, 0], [1.0, 0.5, 0.0], atol=1e-12)

    def test_multi_sample(self):
        """Multiple samples through the encoder."""
        bins = [np.array([0.0, 1.0, 2.0])]
        enc = PiecewiseLinearEncoder(bins)
        X = np.array([[0.5], [1.5]])
        result = enc.encode_structured(X)
        assert result.shape == (2, 1, 2)
        np.testing.assert_allclose(result[0, 0], [0.5, 0.0], atol=1e-12)
        np.testing.assert_allclose(result[1, 0], [1.0, 0.5], atol=1e-12)

    def test_on_edge_values(self):
        """Values exactly at bin edges."""
        bins = [np.array([0.0, 1.0, 2.0])]
        enc = PiecewiseLinearEncoder(bins)

        # Left edge x=0.0
        r = enc.encode_structured(np.array([[0.0]]))
        np.testing.assert_allclose(r[0, 0], [0.0, 0.0], atol=1e-12)

        # Middle edge x=1.0
        r = enc.encode_structured(np.array([[1.0]]))
        np.testing.assert_allclose(r[0, 0], [1.0, 0.0], atol=1e-12)

        # Right edge x=2.0
        r = enc.encode_structured(np.array([[2.0]]))
        np.testing.assert_allclose(r[0, 0], [1.0, 1.0], atol=1e-12)

    def test_extrapolation(self):
        """Values outside the bin range."""
        bins = [np.array([1.0, 2.0, 3.0])]
        enc = PiecewiseLinearEncoder(bins)

        # Below range: x=0.0
        r = enc.encode_structured(np.array([[0.0]]))
        np.testing.assert_allclose(r[0, 0], [-1.0, 0.0], atol=1e-12)

        # Above range: x=4.0
        r = enc.encode_structured(np.array([[4.0]]))
        np.testing.assert_allclose(r[0, 0], [1.0, 2.0], atol=1e-12)


class TestEncoderLayout:
    def test_structured_different_bins(self):
        """Features with different bin counts: padding in the middle."""
        # Feature 0: 3 bins, Feature 1: 1 bin -> max_n_bins=3
        bins = [np.array([0.0, 1.0, 2.0, 3.0]), np.array([0.0, 5.0])]
        enc = PiecewiseLinearEncoder(bins)
        assert enc.n_features == 2
        assert enc.max_n_bins == 3
        assert enc.total_n_bins == 4

        X = np.array([[1.5, 2.5]])
        result = enc.encode_structured(X)
        assert result.shape == (1, 2, 3)

        # Feature 0 (3 bins, edges [0,1,2,3]):
        np.testing.assert_allclose(result[0, 0], [1.0, 0.5, 0.0], atol=1e-12)

        # Feature 1 (1 bin, edges [0,5]):
        # Only last position has the component, rest are 0
        np.testing.assert_allclose(result[0, 1], [0.0, 0.0, 0.5], atol=1e-12)

    def test_three_features_mixed_bins(self):
        """Three features with 4, 1, and 2 bins respectively."""
        bins = [
            np.array([0.0, 1.0, 2.0, 3.0, 4.0]),  # 4 bins
            np.array([0.0, 5.0]),                    # 1 bin
            np.array([0.0, 2.0, 4.0]),               # 2 bins
        ]
        enc = PiecewiseLinearEncoder(bins)
        assert enc.n_features == 3
        assert enc.max_n_bins == 4
        assert enc.total_n_bins == 7

        X = np.array([[2.0, 2.5, 1.0]])
        result = enc.encode_structured(X)
        assert result.shape == (1, 3, 4)

        # Feature 0 (4 bins, max_n_bins=4, no padding):
        np.testing.assert_allclose(result[0, 0], [1.0, 1.0, 0.0, 0.0],
                                   atol=1e-12)

        # Feature 1 (1 bin, edges [0,5]): only position 3 is active
        np.testing.assert_allclose(result[0, 1], [0.0, 0.0, 0.0, 0.5],
                                   atol=1e-12)

        # Feature 2 (2 bins, edges [0,2,4]):
        # Leading 1 component at position 0, last at position 3
        np.testing.assert_allclose(result[0, 2], [0.5, 0.0, 0.0, 0.0],
                                   atol=1e-12)


class TestEncoderSingleBin:
    def test_single_bin_no_clamp(self):
        """Single-bin feature: the sole component is unclamped."""
        bins = [np.array([0.0, 10.0])]
        enc = PiecewiseLinearEncoder(bins)
        assert enc.max_n_bins == 1

        # Below range: should give negative (no clamping)
        r = enc.encode_structured(np.array([[-5.0]]))
        np.testing.assert_allclose(r[0, 0], [-0.5], atol=1e-12)

        # Above range: should give > 1 (no clamping)
        r = enc.encode_structured(np.array([[15.0]]))
        np.testing.assert_allclose(r[0, 0], [1.5], atol=1e-12)

    def test_single_bin_mixed_with_multi(self):
        """Single-bin feature in a mix: last position is unclamped."""
        bins = [np.array([0.0, 1.0, 2.0]), np.array([0.0, 10.0])]
        enc = PiecewiseLinearEncoder(bins)
        assert enc.max_n_bins == 2

        # Feature 1 (1 bin): value well outside range
        r = enc.encode_structured(np.array([[1.0, -10.0]]))
        np.testing.assert_allclose(r[0, 1, -1], -1.0, atol=1e-12)


class TestEncoderFlat:
    def test_flat_different_bins(self):
        """Flat output with features having different bin counts."""
        bins = [np.array([0.0, 1.0, 2.0, 3.0]), np.array([0.0, 5.0])]
        enc = PiecewiseLinearEncoder(bins)
        X = np.array([[1.5, 2.5]])
        flat = enc.encode_flat(X)
        assert flat.shape == (1, 4)  # total_n_bins = 3 + 1
        np.testing.assert_allclose(flat[0], [1.0, 0.5, 0.0, 0.5], atol=1e-12)

    def test_flat_all_same_bins(self):
        """When all features share bin count, flat == flatten of structured."""
        bins = [np.array([0.0, 1.0, 2.0]), np.array([0.0, 3.0, 6.0])]
        enc = PiecewiseLinearEncoder(bins)
        X = np.array([[0.5, 1.5]])
        structured = enc.encode_structured(X)
        flat = enc.encode_flat(X)
        np.testing.assert_allclose(flat, structured.reshape(1, -1), atol=1e-12)

    def test_flat_three_features(self):
        """Flat output for 3 features with 4, 1, 2 bins."""
        bins = [
            np.array([0.0, 1.0, 2.0, 3.0, 4.0]),
            np.array([0.0, 5.0]),
            np.array([0.0, 2.0, 4.0]),
        ]
        enc = PiecewiseLinearEncoder(bins)
        X = np.array([[2.0, 2.5, 1.0]])
        flat = enc.encode_flat(X)
        assert flat.shape == (1, 7)
        np.testing.assert_allclose(flat[0],
                                   [1.0, 1.0, 0.0, 0.0, 0.5, 0.5, 0.0],
                                   atol=1e-12)


class TestEncoderProperties:
    def test_properties(self):
        bins = [
            np.array([0.0, 1.0, 2.0, 3.0]),  # 3 bins
            np.array([0.0, 5.0]),              # 1 bin
            np.array([0.0, 2.0, 4.0]),         # 2 bins
        ]
        enc = PiecewiseLinearEncoder(bins)
        assert enc.n_features == 3
        assert enc.max_n_bins == 3
        assert enc.total_n_bins == 6

    def test_validation_wrong_features(self):
        bins = [np.array([0.0, 1.0])]
        enc = PiecewiseLinearEncoder(bins)
        with pytest.raises(ValueError):
            enc.encode_structured(np.array([[1.0, 2.0]]))  # 2 features, expect 1


class TestCLI:
    def test_structured_output(self):
        X = np.column_stack([
            np.arange(10).astype(np.float64),
            np.arange(10, 20).astype(np.float64),
        ])
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = os.path.join(tmpdir, "input.npy")
            out = os.path.join(tmpdir, "output.npy")
            np.save(inp, X)
            result = subprocess.run(
                ["python3", "/app/ple_encode.py",
                 "--input", inp, "--n-bins", "4",
                 "--format", "structured", "--output", out],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"CLI failed: {result.stderr}"
            output = np.load(out)
            assert output.ndim == 3
            assert output.shape[0] == 10
            assert output.shape[1] == 2
            assert output.shape[2] == 4  # n_bins=4, all unique -> 4 bins

    def test_flat_output(self):
        X = np.column_stack([
            np.arange(10).astype(np.float64),
            np.arange(10, 20).astype(np.float64),
        ])
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = os.path.join(tmpdir, "input.npy")
            out = os.path.join(tmpdir, "output.npy")
            np.save(inp, X)
            result = subprocess.run(
                ["python3", "/app/ple_encode.py",
                 "--input", inp, "--n-bins", "4",
                 "--format", "flat", "--output", out],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"CLI failed: {result.stderr}"
            output = np.load(out)
            assert output.ndim == 2
            assert output.shape[0] == 10

    def test_cli_values_match_library(self):
        """CLI output must match direct library call."""
        X = np.column_stack([
            np.linspace(0, 5, 20),
            np.linspace(10, 15, 20),
        ])
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = os.path.join(tmpdir, "input.npy")
            out = os.path.join(tmpdir, "output.npy")
            np.save(inp, X)
            subprocess.run(
                ["python3", "/app/ple_encode.py",
                 "--input", inp, "--n-bins", "3",
                 "--format", "structured", "--output", out],
                check=True, capture_output=True
            )
            cli_result = np.load(out)

        bins = compute_bins(X, n_bins=3)
        enc = PiecewiseLinearEncoder(bins)
        lib_result = enc.encode_structured(X)
        np.testing.assert_allclose(cli_result, lib_result, atol=1e-12)


class TestMakefile:
    def test_encode_structured(self):
        """Make encode target produces structured output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X = np.column_stack([np.arange(10.0), np.arange(10.0, 20.0)])
            inp = os.path.join(tmpdir, "input.npy")
            out = os.path.join(tmpdir, "output.npy")
            np.save(inp, X)
            result = subprocess.run(
                ["make", "-C", "/app", "encode",
                 f"INPUT={inp}", "NBINS=4", "FORMAT=structured",
                 f"OUTPUT={out}"],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"make encode failed: {result.stderr}"
            output = np.load(out)
            assert output.ndim == 3
            assert output.shape == (10, 2, 4)

    def test_encode_flat(self):
        """Make encode target produces flat output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X = np.column_stack([np.arange(10.0), np.arange(10.0, 20.0)])
            inp = os.path.join(tmpdir, "input.npy")
            out = os.path.join(tmpdir, "output.npy")
            np.save(inp, X)
            result = subprocess.run(
                ["make", "-C", "/app", "encode",
                 f"INPUT={inp}", "NBINS=4", "FORMAT=flat",
                 f"OUTPUT={out}"],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"make encode failed: {result.stderr}"
            output = np.load(out)
            assert output.ndim == 2
            assert output.shape[0] == 10

    def test_batch(self):
        """Make batch target produces both structured.npy and flat.npy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X = np.column_stack([np.arange(10.0), np.arange(10.0, 20.0)])
            inp = os.path.join(tmpdir, "input.npy")
            outdir = os.path.join(tmpdir, "out")
            os.makedirs(outdir)
            np.save(inp, X)
            result = subprocess.run(
                ["make", "-C", "/app", "batch",
                 f"INPUT={inp}", "NBINS=4", f"OUTDIR={outdir}"],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"make batch failed: {result.stderr}"
            s_path = os.path.join(outdir, "structured.npy")
            f_path = os.path.join(outdir, "flat.npy")
            assert os.path.exists(s_path), "structured.npy not produced"
            assert os.path.exists(f_path), "flat.npy not produced"
            s = np.load(s_path)
            f = np.load(f_path)
            assert s.ndim == 3
            assert s.shape == (10, 2, 4)
            assert f.ndim == 2
            assert f.shape == (10, 8)

    def test_report(self):
        """Make report target produces valid report.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X = np.column_stack([np.arange(10.0), np.arange(10.0, 20.0)])
            inp = os.path.join(tmpdir, "input.npy")
            outdir = os.path.join(tmpdir, "out")
            os.makedirs(outdir)
            np.save(inp, X)
            result = subprocess.run(
                ["make", "-C", "/app", "report",
                 f"INPUT={inp}", "NBINS=4", f"OUTDIR={outdir}"],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"make report failed: {result.stderr}"
            report_path = os.path.join(outdir, "report.json")
            assert os.path.exists(report_path), "report.json not produced"
            with open(report_path) as fh:
                report = json.load(fh)
            assert report["n_samples"] == 10
            assert report["n_features"] == 2
            assert report["n_bins_requested"] == 4
            assert report["structured_shape"] == [10, 2, 4]
            assert report["flat_width"] == 8

    def test_clean(self):
        """Make clean target removes generated files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X = np.column_stack([np.arange(10.0), np.arange(10.0, 20.0)])
            inp = os.path.join(tmpdir, "input.npy")
            outdir = os.path.join(tmpdir, "out")
            os.makedirs(outdir)
            np.save(inp, X)
            # Generate files via report (which runs batch first)
            subprocess.run(
                ["make", "-C", "/app", "report",
                 f"INPUT={inp}", "NBINS=4", f"OUTDIR={outdir}"],
                capture_output=True, text=True, check=True
            )
            assert os.path.exists(os.path.join(outdir, "structured.npy"))
            assert os.path.exists(os.path.join(outdir, "report.json"))
            # Now clean
            result = subprocess.run(
                ["make", "-C", "/app", "clean", f"OUTDIR={outdir}"],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"make clean failed: {result.stderr}"
            assert not os.path.exists(os.path.join(outdir, "structured.npy"))
            assert not os.path.exists(os.path.join(outdir, "flat.npy"))
            assert not os.path.exists(os.path.join(outdir, "report.json"))

    def test_encode_values_match_library(self):
        """Make encode output matches direct library call."""
        X = np.column_stack([
            np.linspace(0, 5, 20),
            np.linspace(10, 15, 20),
        ])
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = os.path.join(tmpdir, "input.npy")
            out = os.path.join(tmpdir, "output.npy")
            np.save(inp, X)
            subprocess.run(
                ["make", "-C", "/app", "encode",
                 f"INPUT={inp}", "NBINS=3", "FORMAT=structured",
                 f"OUTPUT={out}"],
                check=True, capture_output=True
            )
            make_result = np.load(out)

        bins = compute_bins(X, n_bins=3)
        enc = PiecewiseLinearEncoder(bins)
        lib_result = enc.encode_structured(X)
        np.testing.assert_allclose(make_result, lib_result, atol=1e-12)


class TestMakefileSweep:
    def _make_test_data(self, tmpdir):
        """Create test data with 100 samples, 2 features."""
        X = np.column_stack([np.arange(100.0), np.arange(100.0, 200.0)])
        inp = os.path.join(tmpdir, "input.npy")
        outdir = os.path.join(tmpdir, "sweep_out")
        os.makedirs(outdir)
        np.save(inp, X)
        return X, inp, outdir

    def test_sweep_creates_all_outputs(self):
        """Sweep target produces outputs for each bin count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X, inp, outdir = self._make_test_data(tmpdir)
            result = subprocess.run(
                ["make", "-C", "/app", "sweep",
                 f"INPUT={inp}", f"OUTDIR={outdir}"],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"make sweep failed: {result.stderr}"

            for n in [4, 8, 16, 32, 64]:
                subdir = os.path.join(outdir, f"bins_{n}")
                assert os.path.isdir(subdir), f"bins_{n}/ not created"
                assert os.path.exists(os.path.join(subdir, "structured.npy")), \
                    f"bins_{n}/structured.npy missing"
                assert os.path.exists(os.path.join(subdir, "flat.npy")), \
                    f"bins_{n}/flat.npy missing"

            sweep_path = os.path.join(outdir, "sweep.json")
            assert os.path.exists(sweep_path), "sweep.json not produced"

    def test_sweep_json_structure(self):
        """Sweep JSON contains correct keys and shapes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X, inp, outdir = self._make_test_data(tmpdir)
            subprocess.run(
                ["make", "-C", "/app", "sweep",
                 f"INPUT={inp}", f"OUTDIR={outdir}"],
                check=True, capture_output=True
            )

            with open(os.path.join(outdir, "sweep.json")) as fh:
                sweep = json.load(fh)

            assert set(sweep.keys()) == {"4", "8", "16", "32", "64"}
            for key in sweep:
                entry = sweep[key]
                assert "structured_shape" in entry, \
                    f"sweep[{key}] missing structured_shape"
                assert "flat_width" in entry, \
                    f"sweep[{key}] missing flat_width"
                shape = entry["structured_shape"]
                assert len(shape) == 3
                assert shape[0] == 100  # n_samples
                assert shape[1] == 2   # n_features

    def test_sweep_values_match_library(self):
        """Sweep encoded outputs match direct library calls."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X, inp, outdir = self._make_test_data(tmpdir)
            subprocess.run(
                ["make", "-C", "/app", "sweep",
                 f"INPUT={inp}", f"OUTDIR={outdir}"],
                check=True, capture_output=True
            )

            for n in [4, 8, 16, 32, 64]:
                bins = compute_bins(X, n_bins=n)
                enc = PiecewiseLinearEncoder(bins)
                expected_s = enc.encode_structured(X)
                expected_f = enc.encode_flat(X)

                actual_s = np.load(
                    os.path.join(outdir, f"bins_{n}", "structured.npy"))
                actual_f = np.load(
                    os.path.join(outdir, f"bins_{n}", "flat.npy"))

                np.testing.assert_allclose(
                    actual_s, expected_s, atol=1e-12,
                    err_msg=f"structured mismatch for n_bins={n}")
                np.testing.assert_allclose(
                    actual_f, expected_f, atol=1e-12,
                    err_msg=f"flat mismatch for n_bins={n}")

    def test_sweep_json_flat_width_correct(self):
        """Sweep JSON flat_width matches actual flat array width."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X, inp, outdir = self._make_test_data(tmpdir)
            subprocess.run(
                ["make", "-C", "/app", "sweep",
                 f"INPUT={inp}", f"OUTDIR={outdir}"],
                check=True, capture_output=True
            )

            with open(os.path.join(outdir, "sweep.json")) as fh:
                sweep = json.load(fh)

            for key in sweep:
                n = int(key)
                flat = np.load(
                    os.path.join(outdir, f"bins_{n}", "flat.npy"))
                assert sweep[key]["flat_width"] == flat.shape[1], \
                    f"flat_width mismatch for n_bins={n}"

    def test_clean_removes_sweep_artifacts(self):
        """Clean target removes sweep subdirectories and sweep.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X, inp, outdir = self._make_test_data(tmpdir)
            subprocess.run(
                ["make", "-C", "/app", "sweep",
                 f"INPUT={inp}", f"OUTDIR={outdir}"],
                check=True, capture_output=True
            )
            assert os.path.exists(os.path.join(outdir, "sweep.json"))
            assert os.path.isdir(os.path.join(outdir, "bins_4"))
            assert os.path.isdir(os.path.join(outdir, "bins_64"))

            result = subprocess.run(
                ["make", "-C", "/app", "clean", f"OUTDIR={outdir}"],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"make clean failed: {result.stderr}"
            assert not os.path.exists(os.path.join(outdir, "sweep.json"))
            assert not os.path.isdir(os.path.join(outdir, "bins_4"))
            assert not os.path.isdir(os.path.join(outdir, "bins_8"))
            assert not os.path.isdir(os.path.join(outdir, "bins_16"))
            assert not os.path.isdir(os.path.join(outdir, "bins_32"))
            assert not os.path.isdir(os.path.join(outdir, "bins_64"))
