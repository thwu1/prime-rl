"""
Verify the ADIOS2 multi-source data fusion pipeline produces correct outputs.

"""
import json
import os

import numpy as np
import pytest

# ── Target grid (velocity sensor) ──
TARGET_NX, TARGET_NY = 64, 48
NUM_FUSED_STEPS = 8
FUSED_DT = 0.1

# ── Temperature source parameters ──
TEMP_NX, TEMP_NY = 32, 24
TEMP_NSTEPS = 4
TEMP_DT = 0.2

# ── Pressure source parameters ──
PRESS_NX, PRESS_NY = 16, 12
PRESS_NSTEPS = 6
PRESS_DT = 0.125

ANOMALY_THRESHOLD = 400.0


# ════════════════════════════════════════════════════════════════════
# Reference computation helpers
# ════════════════════════════════════════════════════════════════════

def _velocity_fields(step):
    """Velocity at a given fused step (same as source — no interpolation)."""
    t = step * FUSED_DT
    i = np.arange(TARGET_NX, dtype=np.float64)
    j = np.arange(TARGET_NY, dtype=np.float64)
    ii, jj = np.meshgrid(i, j, indexing="ij")
    Ux = np.sin(2.0 * np.pi * ii / TARGET_NX) * np.cos(2.0 * np.pi * t)
    Uy = np.cos(2.0 * np.pi * jj / TARGET_NY) * np.sin(2.0 * np.pi * t)
    return Ux, Uy


def _temp_source_field(source_step):
    """Temperature field at a given source step (native resolution)."""
    t = source_step * TEMP_DT
    i = np.arange(TEMP_NX, dtype=np.float64)
    j = np.arange(TEMP_NY, dtype=np.float64)
    ii, jj = np.meshgrid(i, j, indexing="ij")
    T = (300.0
         + 50.0 * np.sin(np.pi * ii / TEMP_NX)
         * np.sin(np.pi * jj / TEMP_NY)
         * np.exp(-0.5 * t))
    if source_step == 2:
        T[16, 12] += 500.0
    return T


def _press_source_field(source_step):
    """Pressure field at a given source step (native resolution)."""
    t = source_step * PRESS_DT
    i = np.arange(PRESS_NX, dtype=np.float64)
    j = np.arange(PRESS_NY, dtype=np.float64)
    ii, jj = np.meshgrid(i, j, indexing="ij")
    P = 101325.0 + 2000.0 * np.cos(2.0 * np.pi * ii / PRESS_NX) * (1.0 - 0.2 * t)
    return P


def _bilinear_upsample(src, Tx, Ty):
    """Corner-aligned bilinear interpolation from src to (Tx, Ty)."""
    Sx, Sy = src.shape
    it_arr = np.arange(Tx, dtype=np.float64)
    jt_arr = np.arange(Ty, dtype=np.float64)

    xs = it_arr * (Sx - 1) / (Tx - 1)
    ys = jt_arr * (Sy - 1) / (Ty - 1)

    x0 = np.floor(xs).astype(int)
    x1 = np.minimum(x0 + 1, Sx - 1)
    y0 = np.floor(ys).astype(int)
    y1 = np.minimum(y0 + 1, Sy - 1)

    fx = (xs - x0)[:, np.newaxis]
    fy = (ys - y0)[np.newaxis, :]

    return (
        (1 - fx) * (1 - fy) * src[np.ix_(x0, y0)]
        + fx * (1 - fy) * src[np.ix_(x1, y0)]
        + (1 - fx) * fy * src[np.ix_(x0, y1)]
        + fx * fy * src[np.ix_(x1, y1)]
    )


def _temporal_interp(target_time, source_times, source_fn):
    """Linear temporal interpolation with boundary clamping."""
    if target_time <= source_times[0]:
        return source_fn(0)
    if target_time >= source_times[-1]:
        return source_fn(len(source_times) - 1)
    for idx in range(len(source_times) - 1):
        if source_times[idx] <= target_time <= source_times[idx + 1]:
            w = ((target_time - source_times[idx])
                 / (source_times[idx + 1] - source_times[idx]))
            return (1 - w) * source_fn(idx) + w * source_fn(idx + 1)
    return source_fn(len(source_times) - 1)


def _fused_temperature(fused_step):
    """Expected fused temperature at a given step (temporal then spatial)."""
    t = fused_step * FUSED_DT
    source_times = [s * TEMP_DT for s in range(TEMP_NSTEPS)]
    src = _temporal_interp(t, source_times, _temp_source_field)
    return _bilinear_upsample(src, TARGET_NX, TARGET_NY)


def _fused_pressure(fused_step):
    """Expected fused pressure at a given step (temporal then spatial)."""
    t = fused_step * FUSED_DT
    source_times = [s * PRESS_DT for s in range(PRESS_NSTEPS)]
    src = _temporal_interp(t, source_times, _press_source_field)
    return _bilinear_upsample(src, TARGET_NX, TARGET_NY)


# ════════════════════════════════════════════════════════════════════
# BP5 File Structure
# ════════════════════════════════════════════════════════════════════

class TestFusedStructure:
    """Verify fused.bp exists and is a valid BP5 dataset."""

    def test_fused_bp_exists(self):
        assert os.path.isdir("/app/fused.bp"), "fused.bp directory not found"

    def test_bp5_format_marker(self):
        assert os.path.exists("/app/fused.bp/mmd.0"), (
            "mmd.0 not found — file may not be BP5 format"
        )

    def test_metadata_index(self):
        assert os.path.exists("/app/fused.bp/md.idx"), "md.idx index missing"

    def test_required_variables(self):
        import adios2
        reader = adios2.FileReader("/app/fused.bp")
        vars_info = reader.available_variables()
        reader.close()
        required = [
            "velocity/Ux", "velocity/Uy", "temperature", "pressure",
            "derived/vorticity", "derived/kinetic_energy", "derived/speed",
            "physical_time",
        ]
        for v in required:
            assert v in vars_info, f"Variable '{v}' missing from fused.bp"

    def test_field_shapes(self):
        import adios2
        reader = adios2.FileReader("/app/fused.bp")
        vars_info = reader.available_variables()
        reader.close()
        fields = [
            "velocity/Ux", "velocity/Uy", "temperature", "pressure",
            "derived/vorticity", "derived/kinetic_energy", "derived/speed",
        ]
        for v in fields:
            shape = [int(x) for x in vars_info[v]["Shape"].split(",") if x.strip()]
            assert shape == [TARGET_NX, TARGET_NY], (
                f"{v} shape {shape} != [{TARGET_NX}, {TARGET_NY}]"
            )

    def test_field_types(self):
        import adios2
        reader = adios2.FileReader("/app/fused.bp")
        vars_info = reader.available_variables()
        reader.close()
        fields = [
            "velocity/Ux", "velocity/Uy", "temperature", "pressure",
            "derived/vorticity", "derived/kinetic_energy", "derived/speed",
        ]
        for v in fields:
            assert vars_info[v]["Type"] == "double", (
                f"{v} type is {vars_info[v]['Type']}, expected double"
            )

    def test_step_count(self):
        import adios2
        reader = adios2.FileReader("/app/fused.bp")
        vars_info = reader.available_variables()
        reader.close()
        steps = int(vars_info["velocity/Ux"]["AvailableStepsCount"])
        assert steps == NUM_FUSED_STEPS, (
            f"Step count {steps} != {NUM_FUSED_STEPS}"
        )


# ════════════════════════════════════════════════════════════════════
# Velocity Data (passthrough from source)
# ════════════════════════════════════════════════════════════════════

class TestVelocityData:
    """Velocity fields should match the velocity sensor directly."""

    @pytest.fixture(autouse=True)
    def setup(self):
        import adios2
        self.reader = adios2.FileReader("/app/fused.bp")
        yield
        self.reader.close()

    @pytest.mark.parametrize("step", [0, 3, 7])
    def test_velocity_ux(self, step):
        data = self.reader.read("velocity/Ux", step_selection=[step, 1])
        Ux, _ = _velocity_fields(step)
        np.testing.assert_allclose(data, Ux, atol=1e-10)

    @pytest.mark.parametrize("step", [0, 4, 7])
    def test_velocity_uy(self, step):
        data = self.reader.read("velocity/Uy", step_selection=[step, 1])
        _, Uy = _velocity_fields(step)
        np.testing.assert_allclose(data, Uy, atol=1e-10)


# ════════════════════════════════════════════════════════════════════
# Temperature Interpolation
# ════════════════════════════════════════════════════════════════════

class TestTemperatureInterpolation:
    """Temperature must be temporally interpolated then spatially upsampled."""

    @pytest.fixture(autouse=True)
    def setup(self):
        import adios2
        self.reader = adios2.FileReader("/app/fused.bp")
        yield
        self.reader.close()

    def test_temperature_step0_exact_match(self):
        """t=0.0 matches source time exactly — no temporal interpolation."""
        data = self.reader.read("temperature", step_selection=[0, 1])
        expected = _fused_temperature(0)
        np.testing.assert_allclose(data, expected, atol=1e-8)

    def test_temperature_step1_temporal_interp(self):
        """t=0.1 between source t=0.0 and t=0.2 — requires temporal interp."""
        data = self.reader.read("temperature", step_selection=[1, 1])
        expected = _fused_temperature(1)
        np.testing.assert_allclose(data, expected, atol=1e-8)

    def test_temperature_step4_anomalous(self):
        """t=0.4 maps to anomalous source step — max should exceed 400K."""
        data = self.reader.read("temperature", step_selection=[4, 1])
        expected = _fused_temperature(4)
        np.testing.assert_allclose(data, expected, atol=1e-8)
        assert np.max(data) > ANOMALY_THRESHOLD

    def test_temperature_step7_clamped(self):
        """t=0.7 exceeds source range — must clamp to last source step."""
        data = self.reader.read("temperature", step_selection=[7, 1])
        expected = _fused_temperature(7)
        np.testing.assert_allclose(data, expected, atol=1e-8)


# ════════════════════════════════════════════════════════════════════
# Pressure Interpolation
# ════════════════════════════════════════════════════════════════════

class TestPressureInterpolation:
    """Pressure must be temporally interpolated then spatially upsampled."""

    @pytest.fixture(autouse=True)
    def setup(self):
        import adios2
        self.reader = adios2.FileReader("/app/fused.bp")
        yield
        self.reader.close()

    def test_pressure_step0_exact_match(self):
        data = self.reader.read("pressure", step_selection=[0, 1])
        expected = _fused_pressure(0)
        np.testing.assert_allclose(data, expected, atol=1e-8)

    def test_pressure_step3_temporal_interp(self):
        """t=0.3 between source t=0.25 and t=0.375 — temporal interp needed."""
        data = self.reader.read("pressure", step_selection=[3, 1])
        expected = _fused_pressure(3)
        np.testing.assert_allclose(data, expected, atol=1e-8)

    def test_pressure_step7_clamped(self):
        """t=0.7 exceeds source range — must clamp to last step."""
        data = self.reader.read("pressure", step_selection=[7, 1])
        expected = _fused_pressure(7)
        np.testing.assert_allclose(data, expected, atol=1e-8)


# ════════════════════════════════════════════════════════════════════
# Derived Variables
# ════════════════════════════════════════════════════════════════════

class TestDerivedVariables:
    """Derived fields computed from fused velocity."""

    @pytest.fixture(autouse=True)
    def setup(self):
        import adios2
        self.reader = adios2.FileReader("/app/fused.bp")
        yield
        self.reader.close()

    @pytest.mark.parametrize("step", [0, 3, 5])
    def test_speed(self, step):
        data = self.reader.read("derived/speed", step_selection=[step, 1])
        Ux, Uy = _velocity_fields(step)
        expected = np.sqrt(Ux ** 2 + Uy ** 2)
        np.testing.assert_allclose(data, expected, atol=1e-10)

    @pytest.mark.parametrize("step", [0, 2, 6])
    def test_kinetic_energy(self, step):
        data = self.reader.read(
            "derived/kinetic_energy", step_selection=[step, 1]
        )
        Ux, Uy = _velocity_fields(step)
        expected = 0.5 * (Ux ** 2 + Uy ** 2)
        np.testing.assert_allclose(data, expected, atol=1e-10)

    @pytest.mark.parametrize("step", [0, 4, 7])
    def test_vorticity(self, step):
        data = self.reader.read("derived/vorticity", step_selection=[step, 1])
        Ux, Uy = _velocity_fields(step)
        dUy_dx = np.gradient(Uy, axis=0)
        dUx_dy = np.gradient(Ux, axis=1)
        expected = dUy_dx - dUx_dy
        np.testing.assert_allclose(data, expected, atol=1e-8)


# ════════════════════════════════════════════════════════════════════
# Attributes
# ════════════════════════════════════════════════════════════════════

class TestFusedAttributes:
    """Required ADIOS2 attributes on the fused dataset."""

    @pytest.fixture(autouse=True)
    def setup(self):
        import adios2
        self.reader = adios2.FileReader("/app/fused.bp")
        self.attrs = self.reader.available_attributes()
        yield
        self.reader.close()

    @pytest.mark.parametrize(
        "attr,expected_unit",
        [
            ("velocity/Ux/unit", "m/s"),
            ("velocity/Uy/unit", "m/s"),
            ("temperature/unit", "K"),
            ("pressure/unit", "Pa"),
        ],
    )
    def test_unit_attribute(self, attr, expected_unit):
        assert attr in self.attrs, f"Attribute '{attr}' missing"
        val = self.attrs[attr]["Value"].strip('"')
        assert val == expected_unit

    def test_grid_attributes(self):
        for dim in ["Nx", "Ny"]:
            assert dim in self.attrs, f"Attribute '{dim}' missing"

    def test_physical_time_values(self):
        for step in range(NUM_FUSED_STEPS):
            pt = self.reader.read("physical_time", step_selection=[step, 1])
            np.testing.assert_allclose(
                float(pt), step * FUSED_DT, atol=1e-12
            )


# ════════════════════════════════════════════════════════════════════
# Fusion Report Structure
# ════════════════════════════════════════════════════════════════════

class TestReportStructure:
    """fusion_report.json must have correct schema."""

    @pytest.fixture(autouse=True)
    def setup(self):
        path = "/app/results/fusion_report.json"
        assert os.path.exists(path), "fusion_report.json not found"
        with open(path) as f:
            self.report = json.load(f)

    def test_output_grid(self):
        assert self.report["output_grid"] == [TARGET_NX, TARGET_NY]

    def test_num_fused_steps(self):
        assert self.report["num_fused_steps"] == NUM_FUSED_STEPS

    def test_source_sensors(self):
        expected = {"sensor_velocity", "sensor_temperature", "sensor_pressure"}
        assert set(self.report["source_sensors"]) == expected

    def test_per_step_stats_count(self):
        assert len(self.report["per_step_stats"]) == NUM_FUSED_STEPS

    def test_per_step_stats_keys(self):
        required_keys = {
            "step", "time", "max_speed", "max_speed_location",
            "mean_temperature", "mean_pressure", "max_abs_vorticity",
            "temperature_anomaly_detected",
        }
        for entry in self.report["per_step_stats"]:
            assert required_keys.issubset(entry.keys()), (
                f"Missing keys in per_step_stats entry: "
                f"{required_keys - entry.keys()}"
            )


# ════════════════════════════════════════════════════════════════════
# Fusion Report Values
# ════════════════════════════════════════════════════════════════════

class TestReportValues:
    """Verify anomaly detection and computed statistics."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with open("/app/results/fusion_report.json") as f:
            self.report = json.load(f)

    def test_anomaly_threshold(self):
        assert self.report["anomaly_threshold"] == ANOMALY_THRESHOLD

    def test_anomalous_steps(self):
        """Steps 3, 4, 5 should be flagged — anomaly propagates via interp."""
        assert sorted(self.report["anomalous_steps"]) == [3, 4, 5]

    @pytest.mark.parametrize("step", [0, 3, 7])
    def test_max_speed(self, step):
        Ux, Uy = _velocity_fields(step)
        speed = np.sqrt(Ux ** 2 + Uy ** 2)
        expected = round(float(np.max(speed)), 6)
        actual = self.report["per_step_stats"][step]["max_speed"]
        assert abs(actual - expected) < 1e-4, (
            f"Step {step}: max_speed {actual} != expected {expected}"
        )

    @pytest.mark.parametrize("step", [0, 2, 5])
    def test_mean_temperature(self, step):
        expected_T = _fused_temperature(step)
        expected = round(float(np.mean(expected_T)), 6)
        actual = self.report["per_step_stats"][step]["mean_temperature"]
        assert abs(actual - expected) < 1e-3, (
            f"Step {step}: mean_temp {actual} != expected {expected}"
        )

    @pytest.mark.parametrize("step", [0, 4, 6])
    def test_anomaly_flag(self, step):
        expected_T = _fused_temperature(step)
        expected_flag = bool(np.max(expected_T) > ANOMALY_THRESHOLD)
        actual_flag = self.report["per_step_stats"][step][
            "temperature_anomaly_detected"
        ]
        assert actual_flag == expected_flag, (
            f"Step {step}: anomaly flag {actual_flag} != expected {expected_flag}"
        )

    @pytest.mark.parametrize("step", [0, 1, 6])
    def test_mean_pressure(self, step):
        expected_P = _fused_pressure(step)
        expected = round(float(np.mean(expected_P)), 6)
        actual = self.report["per_step_stats"][step]["mean_pressure"]
        assert abs(actual - expected) < 1e-3, (
            f"Step {step}: mean_pressure {actual} != expected {expected}"
        )
