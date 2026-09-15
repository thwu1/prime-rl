
import json
import os
import sqlite3
import xml.etree.ElementTree as ET

import h5py
import numpy as np
import pytest
from scipy.integrate import solve_ivp


def load_problem():
    with open("/app/problem.json", "r") as f:
        return json.load(f)


def lotka_volterra_rhs(t, y, params):
    alpha = params["alpha"]
    beta = params["beta"]
    gamma = params["gamma"]
    delta = params["delta"]
    return [alpha * y[0] - beta * y[0] * y[1], -gamma * y[1] + delta * y[0] * y[1]]


def reference_at_time(t_end, problem):
    """Compute high-precision reference solution at a given time."""
    params = problem["parameters"]
    y0 = problem["initial_conditions"]

    def rhs(t, y):
        return lotka_volterra_rhs(t, y, params)

    sol = solve_ivp(rhs, [0, t_end], y0, method="DOP853", rtol=1e-12, atol=1e-14)
    return sol.y[:, -1]


def conserved_quantity(y1, y2, params):
    """Volterra first integral: V = delta*y1 + beta*y2 - gamma*ln(y1) - alpha*ln(y2)."""
    alpha = params["alpha"]
    beta = params["beta"]
    gamma = params["gamma"]
    delta = params["delta"]
    return delta * y1 + beta * y2 - gamma * np.log(y1) - alpha * np.log(y2)


# ---------- File existence ----------


class TestFilesExist:
    def test_trajectory_h5_exists(self):
        assert os.path.exists("/app/results/trajectory.h5"), (
            "trajectory.h5 not found in /app/results/"
        )

    def test_summary_exists(self):
        assert os.path.exists("/app/results/summary.json"), (
            "summary.json not found in /app/results/"
        )

    def test_database_exists(self):
        assert os.path.exists("/app/results/benchmark.db"), (
            "benchmark.db not found in /app/results/"
        )

    def test_convergence_svg_exists(self):
        assert os.path.exists("/app/results/convergence.svg"), (
            "convergence.svg not found in /app/results/"
        )


# ---------- HDF5 archive ----------


class TestHDF5:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.problem = load_problem()
        self.h5 = h5py.File("/app/results/trajectory.h5", "r")
        yield
        self.h5.close()

    def test_root_schema_version(self):
        assert "schema_version" in self.h5.attrs, (
            "Root attribute 'schema_version' missing"
        )
        assert self.h5.attrs["schema_version"] == "1.0", (
            f"schema_version must be '1.0', got '{self.h5.attrs['schema_version']}'"
        )

    def test_trajectory_group_exists(self):
        assert "trajectory" in self.h5, "Group '/trajectory' missing from HDF5"
        assert isinstance(self.h5["trajectory"], h5py.Group)

    def test_trajectory_datasets(self):
        grp = self.h5["trajectory"]
        for name in ["times", "mean", "std"]:
            assert name in grp, f"Dataset '/trajectory/{name}' missing"

    def test_trajectory_shapes(self):
        grp = self.h5["trajectory"]
        T = grp["times"].shape[0]
        d = len(self.problem["initial_conditions"])
        assert T >= 100, f"Expected at least 100 time points, got {T}"
        assert grp["mean"].shape == (T, d), (
            f"mean shape {grp['mean'].shape} != ({T}, {d})"
        )
        assert grp["std"].shape == (T, d), (
            f"std shape {grp['std'].shape} != ({T}, {d})"
        )

    def test_trajectory_compression(self):
        """All trajectory datasets must use gzip compression."""
        grp = self.h5["trajectory"]
        for name in ["times", "mean", "std"]:
            ds = grp[name]
            assert ds.compression == "gzip", (
                f"Dataset '/trajectory/{name}' must use gzip compression, "
                f"got {ds.compression}"
            )
            assert ds.compression_opts is not None and ds.compression_opts >= 4, (
                f"Dataset '/trajectory/{name}' gzip level must be >= 4, "
                f"got {ds.compression_opts}"
            )

    def test_trajectory_chunked(self):
        """All trajectory datasets must use chunked storage."""
        grp = self.h5["trajectory"]
        for name in ["times", "mean", "std"]:
            ds = grp[name]
            assert ds.chunks is not None, (
                f"Dataset '/trajectory/{name}' must use chunked storage"
            )

    def test_metadata_group_exists(self):
        assert "metadata" in self.h5, "Group '/metadata' missing from HDF5"
        assert isinstance(self.h5["metadata"], h5py.Group)

    def test_metadata_attributes(self):
        meta = self.h5["metadata"]
        for attr_name in ["output_scale", "solver_type", "prior_order", "num_steps"]:
            assert attr_name in meta.attrs, (
                f"Attribute '{attr_name}' missing from /metadata group"
            )

    def test_metadata_output_scale_type(self):
        val = self.h5["metadata"].attrs["output_scale"]
        assert isinstance(val, (float, np.floating)), (
            f"output_scale must be float, got {type(val)}"
        )
        assert val > 0 and np.isfinite(val), (
            f"output_scale must be positive and finite, got {val}"
        )

    def test_metadata_prior_order_type(self):
        val = self.h5["metadata"].attrs["prior_order"]
        assert isinstance(val, (int, np.integer)), (
            f"prior_order must be int, got {type(val)}"
        )

    def test_metadata_solver_type_value(self):
        val = self.h5["metadata"].attrs["solver_type"]
        assert isinstance(val, (str, bytes)), (
            f"solver_type must be string, got {type(val)}"
        )

    def test_time_endpoints(self):
        times = self.h5["trajectory"]["times"][:]
        t0, t1 = self.problem["time_span"]
        assert abs(times[0] - t0) < 1e-6, (
            f"First time {times[0]} not close to {t0}"
        )
        assert abs(times[-1] - t1) < 0.02, (
            f"Last time {times[-1]} not close to {t1}"
        )


# ---------- SQLite database ----------


class TestDatabase:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.conn = sqlite3.connect("/app/results/benchmark.db")
        self.cursor = self.conn.cursor()
        self.problem = load_problem()
        yield
        self.conn.close()

    def test_trajectory_table_schema(self):
        self.cursor.execute("PRAGMA table_info(trajectory)")
        cols = {row[1] for row in self.cursor.fetchall()}
        for col in ["step_idx", "time", "dim", "mean", "std"]:
            assert col in cols, f"Missing column '{col}' in trajectory table"

    def test_convergence_table_schema(self):
        self.cursor.execute("PRAGMA table_info(convergence)")
        cols = {row[1] for row in self.cursor.fetchall()}
        for col in ["step_size", "terminal_rmse", "num_steps"]:
            assert col in cols, f"Missing column '{col}' in convergence table"

    def test_metadata_table_schema(self):
        self.cursor.execute("PRAGMA table_info(metadata)")
        cols = {row[1] for row in self.cursor.fetchall()}
        for col in ["key", "value"]:
            assert col in cols, f"Missing column '{col}' in metadata table"

    def test_metadata_required_keys(self):
        self.cursor.execute("SELECT key FROM metadata")
        keys = {row[0] for row in self.cursor.fetchall()}
        for k in ["output_scale", "solver_type", "prior_order"]:
            assert k in keys, f"Missing metadata key '{k}'"

    def test_convergence_required_step_sizes(self):
        self.cursor.execute("SELECT step_size FROM convergence ORDER BY step_size")
        step_sizes = [row[0] for row in self.cursor.fetchall()]
        for h in [0.005, 0.01, 0.02, 0.04]:
            assert any(abs(s - h) < 1e-6 for s in step_sizes), (
                f"Missing convergence entry for step_size={h}"
            )

    def test_convergence_decreasing_rmse(self):
        self.cursor.execute(
            "SELECT step_size, terminal_rmse FROM convergence ORDER BY step_size DESC"
        )
        rows = self.cursor.fetchall()
        assert len(rows) >= 2, "Need at least 2 convergence entries"
        for i in range(len(rows) - 1):
            h_big, rmse_big = rows[i]
            h_small, rmse_small = rows[i + 1]
            assert rmse_big > rmse_small, (
                f"RMSE at h={h_big} ({rmse_big:.6e}) should exceed "
                f"RMSE at h={h_small} ({rmse_small:.6e})"
            )

    def test_trajectory_db_row_count(self):
        """Trajectory table row count must match T * d from the HDF5."""
        with h5py.File("/app/results/trajectory.h5", "r") as f:
            T = f["trajectory"]["times"].shape[0]
            d = f["trajectory"]["mean"].shape[1]
        self.cursor.execute("SELECT COUNT(*) FROM trajectory")
        db_count = self.cursor.fetchone()[0]
        assert db_count == T * d, (
            f"Expected {T * d} trajectory rows, got {db_count}"
        )


# ---------- Trajectory accuracy (from HDF5) ----------


class TestTrajectory:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.problem = load_problem()
        with h5py.File("/app/results/trajectory.h5", "r") as f:
            self.times = f["trajectory"]["times"][:]
            self.mean = f["trajectory"]["mean"][:]
            self.std = f["trajectory"]["std"][:]

    def test_shape_consistency(self):
        T = len(self.times)
        d = len(self.problem["initial_conditions"])
        assert T >= 100, f"Expected at least 100 time points, got {T}"
        assert self.mean.shape == (T, d), (
            f"Mean shape {self.mean.shape} != ({T}, {d})"
        )
        assert self.std.shape == (T, d), (
            f"Std shape {self.std.shape} != ({T}, {d})"
        )

    def test_initial_conditions(self):
        y0 = self.problem["initial_conditions"]
        np.testing.assert_allclose(self.mean[0], y0, atol=1e-6)

    def test_terminal_accuracy(self):
        terminal_time = float(self.times[-1])
        terminal_mean = self.mean[-1]
        ref = reference_at_time(terminal_time, self.problem)
        rmse = np.sqrt(np.mean((terminal_mean - ref) ** 2))
        assert rmse < 0.05, f"Terminal RMSE {rmse:.6f} exceeds threshold 0.05"

    def test_midpoint_accuracy(self):
        mid_time_target = (
            self.problem["time_span"][0] + self.problem["time_span"][1]
        ) / 2
        mid_idx = np.argmin(np.abs(self.times - mid_time_target))
        mid_time = float(self.times[mid_idx])
        mid_mean = self.mean[mid_idx]
        ref = reference_at_time(mid_time, self.problem)
        rmse = np.sqrt(np.mean((mid_mean - ref) ** 2))
        assert rmse < 0.1, (
            f"Midpoint RMSE {rmse:.6f} at t={mid_time:.2f} exceeds threshold 0.1"
        )

    def test_quarter_accuracy(self):
        t_quarter = self.problem["time_span"][0] + 0.25 * (
            self.problem["time_span"][1] - self.problem["time_span"][0]
        )
        idx = np.argmin(np.abs(self.times - t_quarter))
        t_actual = float(self.times[idx])
        ref = reference_at_time(t_actual, self.problem)
        rmse = np.sqrt(np.mean((self.mean[idx] - ref) ** 2))
        assert rmse < 0.1, (
            f"Quarter-point RMSE {rmse:.6f} at t={t_actual:.2f} exceeds threshold 0.1"
        )

    def test_positive_solution(self):
        assert np.all(self.mean > 0), (
            "Lotka-Volterra solution must remain strictly positive"
        )

    def test_std_positive_and_finite(self):
        assert np.all(self.std[1:] > 0), (
            "Standard deviations must be positive after first time step"
        )
        assert np.all(np.isfinite(self.std)), "Standard deviations must be finite"

    def test_std_varies(self):
        for dim in range(self.std.shape[1]):
            std_col = self.std[1:, dim]
            assert np.std(std_col) > 0, (
                f"Standard deviations for dim {dim} are constant (suspicious)"
            )

    def test_conservation(self):
        params = self.problem["parameters"]
        y1 = self.mean[:, 0]
        y2 = self.mean[:, 1]
        V = conserved_quantity(y1, y2, params)
        V_drift = abs(V[-1] - V[0])
        assert V_drift < 0.5, (
            f"Volterra invariant drift {V_drift:.6f} exceeds threshold 0.5"
        )


# ---------- Gnuplot convergence SVG ----------


class TestConvergenceSVG:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.svg_path = "/app/results/convergence.svg"
        self.problem = load_problem()

    def test_svg_parseable(self):
        """SVG must be valid XML."""
        tree = ET.parse(self.svg_path)
        root = tree.getroot()
        # SVG namespace check
        assert "svg" in root.tag.lower() or root.tag.endswith("}svg"), (
            f"Root element is '{root.tag}', expected SVG"
        )

    def test_svg_nontrivial(self):
        """SVG must have substantial content (not empty/stub)."""
        size = os.path.getsize(self.svg_path)
        assert size > 1000, (
            f"SVG file too small ({size} bytes), likely empty or stub"
        )

    def test_svg_contains_title(self):
        """SVG must contain a title with 'Convergence'."""
        with open(self.svg_path, "r") as f:
            content = f.read()
        assert "Convergence" in content or "convergence" in content, (
            "SVG must contain title with 'Convergence'"
        )

    def test_svg_has_axis_labels(self):
        """SVG must contain axis labels."""
        with open(self.svg_path, "r") as f:
            content = f.read()
        # gnuplot embeds axis labels as text elements
        has_x_label = any(
            kw in content.lower()
            for kw in ["step size", "step_size", "stepsize", "h"]
        )
        has_y_label = any(
            kw in content.lower()
            for kw in ["rmse", "error", "terminal"]
        )
        assert has_x_label, "SVG missing x-axis label (step size)"
        assert has_y_label, "SVG missing y-axis label (RMSE/error)"

    def test_svg_has_reference_slope(self):
        """SVG must contain a reference slope line (convergence order)."""
        with open(self.svg_path, "r") as f:
            content = f.read()
        # The reference slope should be mentioned in the legend or as text
        has_ref = any(
            kw in content.lower()
            for kw in ["reference", "order", "o(h", "slope"]
        )
        assert has_ref, (
            "SVG must contain a reference slope line "
            "(look for 'reference', 'order', 'O(h', or 'slope' in legend/text)"
        )

    def test_svg_has_data_points(self):
        """SVG must contain plotted data (circles, points, or path elements)."""
        tree = ET.parse(self.svg_path)
        svg_str = ET.tostring(tree.getroot(), encoding="unicode")
        # gnuplot SVG uses <circle>, <use>, or <path> for data points
        has_points = (
            "<circle" in svg_str
            or "<use" in svg_str
            or "plot" in svg_str.lower()
            or svg_str.count("<path") > 2
        )
        assert has_points, "SVG must contain plotted data points"


# ---------- JSON summary ----------


class TestSummary:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open("/app/results/summary.json", "r") as f:
            self.summary = json.load(f)
        self.problem = load_problem()

    def test_required_keys(self):
        required = ["terminal_mean", "terminal_std", "output_scale", "num_steps"]
        for key in required:
            assert key in self.summary, f"Missing key '{key}' in summary.json"

    def test_terminal_mean_consistent(self):
        with h5py.File("/app/results/trajectory.h5", "r") as f:
            traj_terminal = f["trajectory"]["mean"][-1, :].tolist()
        summary_terminal = self.summary["terminal_mean"]
        np.testing.assert_allclose(summary_terminal, traj_terminal, atol=1e-8)

    def test_terminal_std_consistent(self):
        with h5py.File("/app/results/trajectory.h5", "r") as f:
            traj_terminal_std = f["trajectory"]["std"][-1, :].tolist()
        summary_terminal_std = self.summary["terminal_std"]
        np.testing.assert_allclose(summary_terminal_std, traj_terminal_std, atol=1e-8)

    def test_output_scale_positive_finite(self):
        sigma = self.summary["output_scale"]
        assert sigma > 0, f"Output scale must be positive, got {sigma}"
        assert np.isfinite(sigma), f"Output scale must be finite, got {sigma}"

    def test_num_steps_reasonable(self):
        h = self.problem["solver"]["step_size"]
        t0, t1 = self.problem["time_span"]
        expected = int(round((t1 - t0) / h))
        actual = self.summary["num_steps"]
        assert abs(actual - expected) <= 5, (
            f"num_steps {actual} far from expected {expected}"
        )
