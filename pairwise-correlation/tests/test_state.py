"""
Tests for the weighted pairwise-complete Pearson correlation program.

"""
import numpy as np
import struct
import subprocess
import os
import tempfile
import pytest

CORRELATION_BIN = "/app/correlation"
TOLERANCE = 1e-9


# ─── Helpers ────────────────────────────────────────────────────────────

def write_corr_file(path, data, weights):
    """Write matrix + weights in CORR binary format."""
    n, m = data.shape
    assert weights.shape == (m,), f"weights shape {weights.shape} != ({m},)"
    with open(path, "wb") as f:
        f.write(b"CORR")
        f.write(struct.pack("<II", n, m))
        f.write(weights.astype("<f8").tobytes())
        f.write(data.astype("<f8").tobytes())


def read_rmat_file(path, n):
    """Read correlation matrix from RMAT binary file."""
    num_pairs = n * (n - 1) // 2
    with open(path, "rb") as f:
        magic = f.read(4)
        assert magic == b"RMAT", f"Bad magic: {magic!r}"
        n_read = struct.unpack("<I", f.read(4))[0]
        assert n_read == n, f"n mismatch: {n_read} != {n}"
        raw = f.read(num_pairs * 8)
        assert len(raw) == num_pairs * 8, f"Short read: {len(raw)} != {num_pairs * 8}"
        values = np.frombuffer(raw, dtype="<f8")
    return values


def reference_correlations(data, weights, min_samples):
    """Compute all pairwise-complete weighted correlations (reference)."""
    n, m = data.shape
    results = {}
    for i in range(n):
        for j in range(i + 1, n):
            # Find valid columns
            valid = ~(np.isnan(data[i]) | np.isnan(data[j]))
            count = int(np.sum(valid))
            if count < min_samples:
                results[(i, j)] = float("nan")
                continue
            xi = data[i, valid].astype(np.float64)
            xj = data[j, valid].astype(np.float64)
            w = weights[valid].astype(np.float64)
            W = np.sum(w)
            if W == 0.0:
                results[(i, j)] = float("nan")
                continue
            wn = w / W
            mu_i = np.sum(wn * xi)
            mu_j = np.sum(wn * xj)
            di = xi - mu_i
            dj = xj - mu_j
            var_i = np.sum(wn * di * di)
            var_j = np.sum(wn * dj * dj)
            cov = np.sum(wn * di * dj)
            if var_i == 0.0 or var_j == 0.0:
                results[(i, j)] = float("nan")
                continue
            r = cov / np.sqrt(var_i * var_j)
            results[(i, j)] = float(r)
    return results


def reference_top_k(corr_dict, k):
    """Get top K pairs sorted by r descending, then (i,j) ascending."""
    pairs = [(i, j, r) for (i, j), r in corr_dict.items() if not np.isnan(r)]
    pairs.sort(key=lambda x: (-x[2], x[0], x[1]))
    return pairs[:k]


def corr_dict_to_array(corr_dict, n):
    """Convert correlation dict to upper-triangle array."""
    num_pairs = n * (n - 1) // 2
    arr = np.full(num_pairs, np.nan)
    idx = 0
    for i in range(n):
        for j in range(i + 1, n):
            arr[idx] = corr_dict[(i, j)]
            idx += 1
    return arr


def parse_stdout(stdout_text):
    """Parse stdout into list of (i, j, r) tuples."""
    lines = stdout_text.strip().split("\n") if stdout_text.strip() else []
    result = []
    for line in lines:
        parts = line.split()
        assert len(parts) == 3, f"Bad line: {line!r}"
        result.append((int(parts[0]), int(parts[1]), float(parts[2])))
    return result


def run_program(input_path, k, min_samples, output_path, timeout=60):
    """Run the correlation program and return stdout."""
    result = subprocess.run(
        [CORRELATION_BIN, input_path, str(k), str(min_samples), output_path],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"Program exited with code {result.returncode}\n"
        f"stderr: {result.stderr}\n"
        f"stdout: {result.stdout}"
    )
    return result.stdout


# ─── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def compile_program():
    """Compile the correlation program before running tests."""
    result = subprocess.run(
        ["make", "-C", "/app", "clean"],
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        ["make", "-C", "/app"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Compilation failed:\n{result.stderr}\n{result.stdout}"
    )
    assert os.path.isfile(CORRELATION_BIN), "Binary not found after make"


# ─── Test Cases ─────────────────────────────────────────────────────────

class TestSimpleNoMissing:
    """Test with a simple matrix, no missing data."""

    def _make_data(self, tmp_path):
        # Rows chosen so all 6 pairwise correlations are distinct and
        # well-separated (minimum gap 0.1), avoiding floating-point
        # sort-order ambiguity.
        #   (0,1)=0.8  (0,2)=-1.0  (0,3)=0.6
        #   (1,2)=-0.8  (1,3)=0.5  (2,3)=-0.6
        data = np.array(
            [
                [1.0, 2.0, 3.0, 4.0, 5.0],
                [1.0, 3.0, 2.0, 5.0, 4.0],
                [5.0, 4.0, 3.0, 2.0, 1.0],  # perfectly anti-correlated with row 0
                [2.0, 5.0, 1.0, 3.0, 9.0],
            ]
        )
        weights = np.ones(5)
        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)
        return data, weights, inp, out

    def test_stdout_top_pairs(self, tmp_path):
        data, weights, inp, out = self._make_data(tmp_path)
        ref = reference_correlations(data, weights, min_samples=3)
        ref_top = reference_top_k(ref, 10)

        stdout = run_program(inp, 10, 3, out)
        parsed = parse_stdout(stdout)

        assert len(parsed) == len(ref_top), (
            f"Expected {len(ref_top)} pairs, got {len(parsed)}"
        )
        for (pi, pj, pr), (ri, rj, rr) in zip(parsed, ref_top):
            assert pi == ri and pj == rj, f"Pair mismatch: ({pi},{pj}) != ({ri},{rj})"
            assert abs(pr - rr) < TOLERANCE, f"r mismatch: {pr} != {rr}"

    def test_binary_output(self, tmp_path):
        data, weights, inp, out = self._make_data(tmp_path)
        n = data.shape[0]
        ref = reference_correlations(data, weights, min_samples=3)
        ref_arr = corr_dict_to_array(ref, n)

        run_program(inp, 10, 3, out)
        out_arr = read_rmat_file(out, n)

        assert len(out_arr) == len(ref_arr)
        for idx in range(len(ref_arr)):
            if np.isnan(ref_arr[idx]):
                assert np.isnan(out_arr[idx]), f"Expected NaN at index {idx}"
            else:
                assert abs(out_arr[idx] - ref_arr[idx]) < TOLERANCE, (
                    f"Mismatch at index {idx}: {out_arr[idx]} != {ref_arr[idx]}"
                )

    def test_constant_row_nan(self, tmp_path):
        """Row 3 replaced with constant → its correlations should be NaN."""
        data = np.array(
            [
                [1.0, 2.0, 3.0, 4.0, 5.0],
                [2.0, 4.0, 6.0, 8.0, 10.0],
                [5.0, 4.0, 3.0, 2.0, 1.0],
                [7.0, 7.0, 7.0, 7.0, 7.0],  # constant
            ]
        )
        weights = np.ones(5)
        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        run_program(inp, 10, 3, out)
        out_arr = read_rmat_file(out, 4)

        # Pair indices: (0,1)=0, (0,2)=1, (0,3)=2, (1,2)=3, (1,3)=4, (2,3)=5
        # Pairs involving row 3 (constant): indices 2, 4, 5 → should be NaN
        for idx in [2, 4, 5]:
            assert np.isnan(out_arr[idx]), (
                f"Expected NaN for pair involving constant row at index {idx}, "
                f"got {out_arr[idx]}"
            )


class TestMissingData:
    """Test with NaN missing values."""

    def test_basic_missing(self, tmp_path):
        data = np.array(
            [
                [1.0, np.nan, 3.0, 4.0, 5.0, 6.0],
                [2.0, 3.0, np.nan, 5.0, 6.0, 7.0],
                [np.nan, np.nan, np.nan, np.nan, np.nan, np.nan],  # all NaN
            ]
        )
        weights = np.ones(6)
        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        ref = reference_correlations(data, weights, min_samples=3)
        ref_top = reference_top_k(ref, 10)

        stdout = run_program(inp, 10, 3, out)
        parsed = parse_stdout(stdout)

        # Only pair (0,1) should be valid
        assert len(parsed) == 1, f"Expected 1 valid pair, got {len(parsed)}"
        assert parsed[0][0] == 0 and parsed[0][1] == 1
        assert abs(parsed[0][2] - ref_top[0][2]) < TOLERANCE

    def test_min_samples_threshold(self, tmp_path):
        """With min_samples=5, pair (0,1) has only 4 valid cols → no output."""
        data = np.array(
            [
                [1.0, np.nan, 3.0, 4.0, 5.0, 6.0],
                [2.0, 3.0, np.nan, 5.0, 6.0, 7.0],
            ]
        )
        weights = np.ones(6)
        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        stdout = run_program(inp, 10, 5, out)
        parsed = parse_stdout(stdout)
        assert len(parsed) == 0, f"Expected 0 pairs with min_samples=5, got {len(parsed)}"

    def test_partial_overlap(self, tmp_path):
        """Pairs have different sets of valid columns."""
        data = np.array(
            [
                [1.0, 2.0, np.nan, 4.0, 5.0],
                [np.nan, 2.0, 3.0, 4.0, 5.0],
                [1.0, np.nan, 3.0, np.nan, 5.0],
            ]
        )
        weights = np.array([1.0, 2.0, 1.5, 0.5, 3.0])
        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        ref = reference_correlations(data, weights, min_samples=2)
        ref_top = reference_top_k(ref, 10)

        stdout = run_program(inp, 10, 2, out)
        parsed = parse_stdout(stdout)

        assert len(parsed) == len(ref_top)
        for (pi, pj, pr), (ri, rj, rr) in zip(parsed, ref_top):
            assert pi == ri and pj == rj
            assert abs(pr - rr) < TOLERANCE, f"r mismatch: {pr} vs {rr}"


class TestWeightedCorrelation:
    """Test that column weights are correctly applied."""

    def test_nonuniform_weights(self, tmp_path):
        """Weighted correlation should differ from unweighted."""
        data = np.array(
            [
                [1.0, 2.0, 3.0, 4.0],
                [4.0, 3.0, 2.0, 1.0],
                [1.0, 3.0, 2.0, 4.0],
            ]
        )
        weights = np.array([10.0, 1.0, 1.0, 10.0])
        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        ref = reference_correlations(data, weights, min_samples=2)

        run_program(inp, 10, 2, out)
        out_arr = read_rmat_file(out, 3)

        ref_arr = corr_dict_to_array(ref, 3)
        for idx in range(len(ref_arr)):
            if np.isnan(ref_arr[idx]):
                assert np.isnan(out_arr[idx])
            else:
                assert abs(out_arr[idx] - ref_arr[idx]) < TOLERANCE, (
                    f"idx={idx}: {out_arr[idx]} != {ref_arr[idx]}"
                )

        # Verify weights actually matter: compute unweighted and check it differs
        ref_unweighted = reference_correlations(data, np.ones(4), min_samples=2)
        ref_unweighted_arr = corr_dict_to_array(ref_unweighted, 3)
        # At least one correlation should differ
        diffs = []
        for idx in range(len(ref_arr)):
            if not np.isnan(ref_arr[idx]) and not np.isnan(ref_unweighted_arr[idx]):
                diffs.append(abs(ref_arr[idx] - ref_unweighted_arr[idx]))
        assert any(d > 1e-6 for d in diffs), (
            "Weighted and unweighted correlations are identical — weights not applied"
        )


class TestRandomMatrix:
    """Test with random data, comparing against reference."""

    def test_medium_no_missing(self, tmp_path):
        rng = np.random.default_rng(12345)
        n, m = 80, 40
        data = rng.standard_normal((n, m))
        weights = rng.uniform(0.5, 3.0, size=m)
        K, min_s = 30, 3

        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        ref = reference_correlations(data, weights, min_s)
        ref_top = reference_top_k(ref, K)

        stdout = run_program(inp, K, min_s, out)
        parsed = parse_stdout(stdout)

        assert len(parsed) == len(ref_top)
        for (pi, pj, pr), (ri, rj, rr) in zip(parsed, ref_top):
            assert pi == ri and pj == rj, f"Pair mismatch: ({pi},{pj}) != ({ri},{rj})"
            assert abs(pr - rr) < TOLERANCE, f"r mismatch: {pr} vs {rr}"

    def test_medium_with_missing(self, tmp_path):
        rng = np.random.default_rng(67890)
        n, m = 60, 50
        data = rng.standard_normal((n, m))
        weights = rng.uniform(0.1, 5.0, size=m)
        # 20% missing
        mask = rng.random((n, m)) < 0.2
        data[mask] = np.nan
        K, min_s = 25, 5

        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        ref = reference_correlations(data, weights, min_s)
        ref_top = reference_top_k(ref, K)
        ref_arr = corr_dict_to_array(ref, n)

        stdout = run_program(inp, K, min_s, out)
        parsed = parse_stdout(stdout)
        out_arr = read_rmat_file(out, n)

        # Check stdout
        assert len(parsed) == len(ref_top)
        for (pi, pj, pr), (ri, rj, rr) in zip(parsed, ref_top):
            assert pi == ri and pj == rj
            assert abs(pr - rr) < TOLERANCE

        # Check binary output
        for idx in range(len(ref_arr)):
            if np.isnan(ref_arr[idx]):
                assert np.isnan(out_arr[idx]), f"Expected NaN at index {idx}"
            else:
                assert abs(out_arr[idx] - ref_arr[idx]) < TOLERANCE, (
                    f"idx={idx}: {out_arr[idx]} != {ref_arr[idx]}"
                )

    def test_larger_matrix(self, tmp_path):
        """Larger test to check correctness at scale."""
        rng = np.random.default_rng(11111)
        n, m = 200, 80
        data = rng.standard_normal((n, m))
        weights = rng.uniform(1.0, 2.0, size=m)
        mask = rng.random((n, m)) < 0.15
        data[mask] = np.nan
        # Make a few rows constant to test edge case
        data[50, :] = 3.14
        data[100, :] = -2.71
        K, min_s = 50, 10

        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        ref = reference_correlations(data, weights, min_s)
        ref_top = reference_top_k(ref, K)

        stdout = run_program(inp, K, min_s, out, timeout=120)
        parsed = parse_stdout(stdout)

        assert len(parsed) == len(ref_top)
        for (pi, pj, pr), (ri, rj, rr) in zip(parsed, ref_top):
            assert pi == ri and pj == rj, f"Pair mismatch: ({pi},{pj}) != ({ri},{rj})"
            assert abs(pr - rr) < TOLERANCE, f"r mismatch at ({pi},{pj}): {pr} vs {rr}"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_two_rows(self, tmp_path):
        data = np.array([[1.0, 2.0, 3.0], [3.0, 5.0, 7.0]])
        weights = np.array([1.0, 1.0, 1.0])
        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        ref = reference_correlations(data, weights, min_samples=2)

        stdout = run_program(inp, 1, 2, out)
        parsed = parse_stdout(stdout)

        assert len(parsed) == 1
        assert parsed[0][0] == 0 and parsed[0][1] == 1
        r_ref = ref[(0, 1)]
        assert abs(parsed[0][2] - r_ref) < TOLERANCE

    def test_k_larger_than_pairs(self, tmp_path):
        """K exceeds the number of valid pairs."""
        data = np.array([[1.0, 2.0, 3.0], [2.0, 4.0, 6.0], [3.0, 3.0, 3.0]])
        weights = np.ones(3)
        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        ref = reference_correlations(data, weights, min_samples=2)
        ref_top = reference_top_k(ref, 100)

        stdout = run_program(inp, 100, 2, out)
        parsed = parse_stdout(stdout)

        assert len(parsed) == len(ref_top)

    def test_all_nan_row(self, tmp_path):
        """One row entirely NaN — all its correlations should be NaN."""
        data = np.array(
            [
                [1.0, 2.0, 3.0, 4.0],
                [2.0, 3.0, 4.0, 5.0],
                [np.nan, np.nan, np.nan, np.nan],
            ]
        )
        weights = np.ones(4)
        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        run_program(inp, 10, 2, out)
        out_arr = read_rmat_file(out, 3)

        # Pairs: (0,1)=idx0, (0,2)=idx1, (1,2)=idx2
        # (0,2) and (1,2) involve all-NaN row → NaN
        assert not np.isnan(out_arr[0]), "Pair (0,1) should be valid"
        assert np.isnan(out_arr[1]), "Pair (0,2) should be NaN"
        assert np.isnan(out_arr[2]), "Pair (1,2) should be NaN"

    def test_sorting_order(self, tmp_path):
        """Verify descending sort by r, then ascending by (i, j)."""
        # Construct data with known distinct correlations
        rng = np.random.default_rng(99999)
        n, m = 10, 20
        data = rng.standard_normal((n, m))
        weights = np.ones(m)

        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        ref = reference_correlations(data, weights, min_samples=3)
        ref_top = reference_top_k(ref, n * (n - 1) // 2)

        stdout = run_program(inp, n * (n - 1) // 2, 3, out)
        parsed = parse_stdout(stdout)

        assert len(parsed) == len(ref_top)
        # Check ordering is correct
        for k in range(len(parsed) - 1):
            r_cur = parsed[k][2]
            r_next = parsed[k + 1][2]
            assert r_cur >= r_next - TOLERANCE, (
                f"Sort violation at position {k}: {r_cur} < {r_next}"
            )
            if abs(r_cur - r_next) < TOLERANCE:
                assert (parsed[k][0], parsed[k][1]) <= (
                    parsed[k + 1][0],
                    parsed[k + 1][1],
                ), f"Tie-break violation at position {k}"

    def test_single_valid_pair_among_many_nan(self, tmp_path):
        """Matrix where most pairs are invalid due to insufficient overlap."""
        data = np.full((5, 10), np.nan)
        # Only rows 0 and 1 share valid columns 0..4
        data[0, :5] = [1.0, 2.0, 3.0, 4.0, 5.0]
        data[1, :5] = [5.0, 4.0, 3.0, 2.0, 1.0]
        # Row 2 valid only in cols 5..9
        data[2, 5:] = [1.0, 2.0, 3.0, 4.0, 5.0]
        # Rows 3 and 4: valid in cols 0..2 and 7..9 respectively
        data[3, :3] = [1.0, 2.0, 3.0]
        data[4, 7:] = [1.0, 2.0, 3.0]
        weights = np.ones(10)

        inp = str(tmp_path / "input.bin")
        out = str(tmp_path / "output.bin")
        write_corr_file(inp, data, weights)

        ref = reference_correlations(data, weights, min_samples=3)
        ref_top = reference_top_k(ref, 20)

        stdout = run_program(inp, 20, 3, out)
        parsed = parse_stdout(stdout)

        assert len(parsed) == len(ref_top)
        for (pi, pj, pr), (ri, rj, rr) in zip(parsed, ref_top):
            assert pi == ri and pj == rj
            assert abs(pr - rr) < TOLERANCE
