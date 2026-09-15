
import pytest
import os
import csv


def _load_max_growth():
    """Load max_growth.csv into a list of dicts."""
    data = []
    with open("/app/results/max_growth.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(
                {
                    "Ri": float(row["Ri"]),
                    "sigma_max": float(row["sigma_max"]),
                    "k_max": float(row["k_max"]),
                }
            )
    return data


def _load_growth_rates():
    """Load growth_rates.csv. Returns (k_values, header_labels, sigma_matrix)."""
    with open("/app/results/growth_rates.csv") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    k_vals = [float(r[0]) for r in rows]
    sigma = [[float(v) for v in r[1:]] for r in rows]
    return k_vals, header[1:], sigma


# ── File existence ──────────────────────────────────────────────


class TestFileExistence:
    def test_growth_rates_exists(self):
        assert os.path.isfile("/app/results/growth_rates.csv")

    def test_max_growth_exists(self):
        assert os.path.isfile("/app/results/max_growth.csv")

    def test_critical_ri_exists(self):
        assert os.path.isfile("/app/results/critical_ri.txt")


# ── Format validation ──────────────────────────────────────────


class TestFormat:
    def test_growth_rates_header(self):
        with open("/app/results/growth_rates.csv") as f:
            header = f.readline().strip().split(",")
        assert header[0].strip() == "k"
        assert len(header) >= 5, "Expected at least k + 4 Ri columns"

    def test_growth_rates_row_count(self):
        k_vals, _, _ = _load_growth_rates()
        assert len(k_vals) >= 50, f"Only {len(k_vals)} wavenumber rows"

    def test_max_growth_columns(self):
        with open("/app/results/max_growth.csv") as f:
            header = f.readline().strip().split(",")
        labels = [h.strip() for h in header]
        assert "Ri" in labels[0]
        assert "sigma_max" in labels[1]
        assert "k_max" in labels[2]

    def test_max_growth_row_count(self):
        data = _load_max_growth()
        assert len(data) >= 4, f"Only {len(data)} Ri rows in max_growth"


# ── Reference-value checks (Michalke 1964, Miles-Howard) ──────


class TestReferenceValues:
    def test_sigma_max_ri_zero(self):
        """Maximum growth rate at Ri=0 should be ~0.1897."""
        data = _load_max_growth()
        ri0 = [d for d in data if abs(d["Ri"]) < 0.01]
        assert len(ri0) >= 1, "No Ri=0 entry found"
        sigma = ri0[0]["sigma_max"]
        assert 0.170 < sigma < 0.210, (
            f"sigma_max(Ri=0) = {sigma:.4f}, expected ~0.1897"
        )

    def test_k_max_ri_zero(self):
        """Most unstable wavenumber at Ri=0 should be ~0.44."""
        data = _load_max_growth()
        ri0 = [d for d in data if abs(d["Ri"]) < 0.01]
        assert len(ri0) >= 1
        k = ri0[0]["k_max"]
        assert 0.30 < k < 0.60, f"k_max(Ri=0) = {k:.4f}, expected ~0.44"

    def test_stability_at_quarter(self):
        """Flow should be effectively stable at Ri=0.25."""
        data = _load_max_growth()
        ri25 = [d for d in data if abs(d["Ri"] - 0.25) < 0.01]
        assert len(ri25) >= 1, "No Ri=0.25 entry found"
        sigma = ri25[0]["sigma_max"]
        assert sigma < 0.01, (
            f"sigma_max(Ri=0.25) = {sigma:.6f}, expected ~0 (Miles-Howard)"
        )

    def test_critical_ri_value(self):
        """Critical Richardson number should be ~0.250."""
        with open("/app/results/critical_ri.txt") as f:
            crit = float(f.read().strip())
        assert 0.20 <= crit <= 0.26, f"Critical Ri = {crit}, expected ~0.250"


# ── Physical consistency ───────────────────────────────────────


class TestPhysicalConsistency:
    def test_monotonicity(self):
        """sigma_max should be non-increasing with Ri."""
        data = _load_max_growth()
        data.sort(key=lambda d: d["Ri"])
        for i in range(1, len(data)):
            assert data[i]["sigma_max"] <= data[i - 1]["sigma_max"] + 2e-3, (
                f"Non-monotonic: sigma({data[i]['Ri']:.2f})="
                f"{data[i]['sigma_max']:.6f} > "
                f"sigma({data[i-1]['Ri']:.2f})="
                f"{data[i-1]['sigma_max']:.6f}"
            )

    def test_nonnegative_growth(self):
        """All reported growth rates should be >= 0 (within noise)."""
        _, _, sigma = _load_growth_rates()
        for i, row in enumerate(sigma):
            for j, val in enumerate(row):
                assert val >= -1e-3, f"Negative growth rate {val} at row {i} col {j}"

    def test_high_k_decay_ri_zero(self):
        """Growth rates at k > 1.0 should be small for Ri=0."""
        k_vals, headers, sigma = _load_growth_rates()
        # Find Ri=0 column
        ri_col = None
        for j, h in enumerate(headers):
            if "0.00" in h:
                ri_col = j
                break
        assert ri_col is not None, "Cannot find Ri=0.00 column"
        for i, k in enumerate(k_vals):
            if k > 1.05:
                assert sigma[i][ri_col] < 0.05, (
                    f"sigma(k={k:.2f}, Ri=0) = {sigma[i][ri_col]:.4f}, "
                    f"expected < 0.05 for large k"
                )

    def test_growth_intermediate_ri(self):
        """Growth rate at Ri=0.10 should be positive but less than at Ri=0."""
        data = _load_max_growth()
        ri0 = [d for d in data if abs(d["Ri"]) < 0.01]
        ri10 = [d for d in data if abs(d["Ri"] - 0.10) < 0.01]
        assert len(ri0) >= 1 and len(ri10) >= 1
        assert ri10[0]["sigma_max"] > 0.01, "Ri=0.10 should still be unstable"
        assert ri10[0]["sigma_max"] < ri0[0]["sigma_max"] + 1e-3, (
            "Ri=0.10 growth should be less than Ri=0"
        )
