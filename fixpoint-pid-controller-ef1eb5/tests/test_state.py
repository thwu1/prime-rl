"""
Verification tests for Q16.16 fixed-point PID controller simulation.

Tests verify the closed-loop trace output against golden reference samples
with a tolerance of +/- 2 LSBs in Q16.16, plus qualitative behavior checks
and source integrity validation.

"""
import os
import re
import pytest

# Tolerance: 2 LSBs in Q16.16
TOLERANCE = 2

# Golden reference samples: step_index -> {ref, y, u, error} as hex strings
# 93 sample points covering pre-step, transients, settling, and step-down
GOLDEN = {
    0:    {"ref":"00000000","y":"00000000","u":"00000000","error":"00000000"},
    50:   {"ref":"00000000","y":"00000000","u":"00000000","error":"00000000"},
    99:   {"ref":"00000000","y":"00000000","u":"00000000","error":"00000000"},
    100:  {"ref":"00010000","y":"00000000","u":"000572de","error":"00010000"},
    101:  {"ref":"00010000","y":"00000000","u":"00056611","error":"00010000"},
    102:  {"ref":"00010000","y":"00000024","u":"0005598f","error":"0000ffdc"},
    103:  {"ref":"00010000","y":"0000006c","u":"00054c93","error":"0000ff94"},
    104:  {"ref":"00010000","y":"000000d7","u":"00053f1c","error":"0000ff29"},
    105:  {"ref":"00010000","y":"00000165","u":"00053131","error":"0000fe9b"},
    106:  {"ref":"00010000","y":"00000215","u":"000522d2","error":"0000fdeb"},
    107:  {"ref":"00010000","y":"000002e6","u":"00051405","error":"0000fd1a"},
    108:  {"ref":"00010000","y":"000003d8","u":"000504ce","error":"0000fc28"},
    109:  {"ref":"00010000","y":"000004ea","u":"0004f52f","error":"0000fb16"},
    110:  {"ref":"00010000","y":"0000061c","u":"0004e52d","error":"0000f9e4"},
    115:  {"ref":"00010000","y":"00000dd9","u":"00048fb6","error":"0000f227"},
    120:  {"ref":"00010000","y":"0000184a","u":"00043283","error":"0000e7b6"},
    125:  {"ref":"00010000","y":"0000251a","u":"0003cf42","error":"0000dae6"},
    130:  {"ref":"00010000","y":"000033f0","u":"000367af","error":"0000cc10"},
    135:  {"ref":"00010000","y":"00004472","u":"0002fd68","error":"0000bb8e"},
    140:  {"ref":"00010000","y":"00005643","u":"00029218","error":"0000a9bd"},
    145:  {"ref":"00010000","y":"0000690b","u":"0002273e","error":"000096f5"},
    150:  {"ref":"00010000","y":"00007c71","u":"0001be55","error":"0000838f"},
    155:  {"ref":"00010000","y":"00009022","u":"000158a7","error":"00006fde"},
    160:  {"ref":"00010000","y":"0000a3cc","u":"0000f77c","error":"00005c34"},
    165:  {"ref":"00010000","y":"0000b723","u":"00009bdf","error":"000048dd"},
    170:  {"ref":"00010000","y":"0000c9e4","u":"000046c5","error":"0000361c"},
    175:  {"ref":"00010000","y":"0000dbce","u":"fffff8fb","error":"00002432"},
    180:  {"ref":"00010000","y":"0000ecab","u":"ffffb326","error":"00001355"},
    185:  {"ref":"00010000","y":"0000fc48","u":"ffff75d2","error":"000003b8"},
    190:  {"ref":"00010000","y":"00010a7e","u":"ffff414c","error":"fffff582"},
    195:  {"ref":"00010000","y":"0001172a","u":"ffff15d5","error":"ffffe8d6"},
    200:  {"ref":"00010000","y":"00012233","u":"fffef381","error":"ffffddcd"},
    210:  {"ref":"00010000","y":"0001331b","u":"fffec9d8","error":"ffffcce5"},
    220:  {"ref":"00010000","y":"00013d00","u":"fffec277","error":"ffffc300"},
    230:  {"ref":"00010000","y":"00014015","u":"fffed9d3","error":"ffffbfeb"},
    250:  {"ref":"00010000","y":"00013459","u":"ffff50b2","error":"ffffcba7"},
    275:  {"ref":"00010000","y":"00010e90","u":"00002f08","error":"fffff170"},
    300:  {"ref":"00010000","y":"0000e07b","u":"00010a4f","error":"00001f85"},
    350:  {"ref":"00010000","y":"0000a6c1","u":"0001d37d","error":"0000593f"},
    400:  {"ref":"00010000","y":"0000b655","u":"000153e9","error":"000049ab"},
    450:  {"ref":"00010000","y":"0000e2af","u":"00009c81","error":"00001d51"},
    500:  {"ref":"00010000","y":"0000f759","u":"00007b80","error":"000008a7"},
    550:  {"ref":"00010000","y":"0000ee4f","u":"0000d0be","error":"000011b1"},
    600:  {"ref":"00010000","y":"0000e0fa","u":"00011720","error":"00001f06"},
    650:  {"ref":"00010000","y":"0000e155","u":"0001133d","error":"00001eab"},
    700:  {"ref":"00010000","y":"0000eba8","u":"0000ec87","error":"00001458"},
    750:  {"ref":"00010000","y":"0000f3e6","u":"0000da5d","error":"00000c1a"},
    800:  {"ref":"00010000","y":"0000f520","u":"0000e73b","error":"00000ae0"},
    850:  {"ref":"00010000","y":"0000f32e","u":"0000fa77","error":"00000cd2"},
    900:  {"ref":"00010000","y":"0000f30b","u":"0000ffff","error":"00000cf5"},
    1000: {"ref":"00010000","y":"0000f84e","u":"0000f46d","error":"000007b2"},
    1100: {"ref":"00010000","y":"0000f9e0","u":"0000fa7a","error":"00000620"},
    1250: {"ref":"00010000","y":"0000fbe3","u":"0000fb99","error":"0000041d"},
    1375: {"ref":"00010000","y":"0000fd05","u":"0000fd97","error":"000002fb"},
    1500: {"ref":"00010000","y":"0000fdee","u":"0000fdf2","error":"00000212"},
    1625: {"ref":"00010000","y":"0000fe7b","u":"0000feb9","error":"00000185"},
    1750: {"ref":"00010000","y":"0000fef8","u":"0000feca","error":"00000108"},
    1875: {"ref":"00010000","y":"0000ff47","u":"0000ff2f","error":"000000b9"},
    2000: {"ref":"00010000","y":"0000ff71","u":"0000ff83","error":"0000008f"},
    2250: {"ref":"00010000","y":"0000ffb5","u":"0000ffe6","error":"0000004b"},
    2500: {"ref":"00010000","y":"0000ffc8","u":"0000ffd1","error":"00000038"},
    2750: {"ref":"00010000","y":"0000ffc8","u":"0000ffd1","error":"00000038"},
    2999: {"ref":"00010000","y":"0000ffc8","u":"0000ffd1","error":"00000038"},
    3000: {"ref":"00008000","y":"0000ffc8","u":"fffe4662","error":"ffff8038"},
    3001: {"ref":"00008000","y":"0000ffc8","u":"fffe4cc9","error":"ffff8038"},
    3002: {"ref":"00008000","y":"0000ffb6","u":"fffe530a","error":"ffff804a"},
    3005: {"ref":"00008000","y":"0000ff16","u":"fffe6739","error":"ffff80ea"},
    3010: {"ref":"00008000","y":"0000fcbb","u":"fffe8d3d","error":"ffff8345"},
    3020: {"ref":"00008000","y":"0000f3a7","u":"fffee68c","error":"ffff8c59"},
    3030: {"ref":"00008000","y":"0000e5d7","u":"ffff4bf2","error":"ffff9a29"},
    3050: {"ref":"00008000","y":"0000c19b","u":"0000209a","error":"ffffbe65"},
    3075: {"ref":"00008000","y":"000091f0","u":"00010346","error":"ffffee10"},
    3100: {"ref":"00008000","y":"00006ebd","u":"00018622","error":"00001143"},
    3125: {"ref":"00008000","y":"0000602a","u":"00019a9a","error":"00001fd6"},
    3150: {"ref":"00008000","y":"000065b0","u":"00015782","error":"00001a50"},
    3175: {"ref":"00008000","y":"00007898","u":"0000e854","error":"00000768"},
    3200: {"ref":"00008000","y":"00008fa5","u":"00007ab4","error":"fffff05b"},
    3250: {"ref":"00008000","y":"0000ac85","u":"00001628","error":"ffffd37b"},
    3300: {"ref":"00008000","y":"0000a4bb","u":"00005605","error":"ffffdb45"},
    3400: {"ref":"00008000","y":"00008443","u":"0000c228","error":"fffffbbd"},
    3500: {"ref":"00008000","y":"00008f74","u":"00007471","error":"fffff08c"},
    3600: {"ref":"00008000","y":"00008a20","u":"000089bb","error":"fffff5e0"},
    3700: {"ref":"00008000","y":"0000856a","u":"00008c4d","error":"fffffa96"},
    3750: {"ref":"00008000","y":"00008660","u":"000082c5","error":"fffff9a0"},
    3800: {"ref":"00008000","y":"00008672","u":"00007ff7","error":"fffff98e"},
    3900: {"ref":"00008000","y":"000083d0","u":"000085c7","error":"fffffc30"},
    4000: {"ref":"00008000","y":"0000830f","u":"000082bb","error":"fffffcf1"},
    4100: {"ref":"00008000","y":"00008291","u":"0000818f","error":"fffffd6f"},
    4250: {"ref":"00008000","y":"0000818a","u":"000081a8","error":"fffffe76"},
    4500: {"ref":"00008000","y":"000080cd","u":"000080b5","error":"ffffff33"},
    4750: {"ref":"00008000","y":"00008075","u":"00008050","error":"ffffff8b"},
    4900: {"ref":"00008000","y":"00008041","u":"0000805d","error":"ffffffbf"},
    4999: {"ref":"00008000","y":"0000802b","u":"00008042","error":"ffffffd5"},
}


def hex_to_signed32(h):
    """Convert 8-char hex string to signed 32-bit integer."""
    val = int(h, 16)
    if val >= 0x80000000:
        val -= 0x100000000
    return val


def load_trace():
    """Load the trace output CSV file."""
    trace_path = "/app/trace_output.csv"
    assert os.path.isfile(trace_path), \
        f"Trace file {trace_path} does not exist. Did the simulation run?"
    data = {}
    with open(trace_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            assert len(parts) == 5, f"Malformed trace line: {line}"
            step = int(parts[0])
            data[step] = {
                "ref": parts[1],
                "y": parts[2],
                "u": parts[3],
                "error": parts[4],
            }
    return data


@pytest.fixture(scope="module")
def trace():
    return load_trace()


class TestTraceFormat:
    def test_trace_file_exists(self):
        assert os.path.isfile("/app/trace_output.csv")

    def test_trace_has_correct_length(self, trace):
        assert len(trace) == 5000, \
            f"Expected 5000 trace steps, got {len(trace)}"

    def test_trace_step_indices(self, trace):
        for k in range(5000):
            assert k in trace, f"Missing step index {k}"

    def test_hex_format(self, trace):
        for k in [0, 100, 200, 3000, 4999]:
            for field in ["ref", "y", "u", "error"]:
                val = trace[k][field]
                assert len(val) == 8, \
                    f"Step {k} field {field}: expected 8 hex chars, got '{val}'"
                int(val, 16)  # must be valid hex


class TestControllerBehavior:
    """Verify qualitative PID controller behavior."""

    def test_zero_output_before_step(self, trace):
        """Output should be zero before the reference step at k=100."""
        for k in [0, 10, 25, 50, 75, 99]:
            y = hex_to_signed32(trace[k]["y"])
            assert y == 0, f"Step {k}: y should be 0, got {y}"

    def test_positive_control_after_step(self, trace):
        """Control signal should be positive right after step-up."""
        u = hex_to_signed32(trace[100]["u"])
        assert u > 0, f"Step 100: control u should be positive, got {u}"

    def test_control_nonzero_range(self, trace):
        """Control signal should be substantial during initial transient."""
        u_100 = hex_to_signed32(trace[100]["u"])
        # 2.5 * 1.0 (Kp * full-scale error) ≈ 163840 Q16.16
        # With integral and derivative, first-step u should exceed pure P
        assert u_100 > 100000, \
            f"Step 100: u={u_100} is too small for a PID with Kp=2.5"

    def test_overshoot_exists(self, trace):
        """Underdamped system should overshoot the reference."""
        y_200 = hex_to_signed32(trace[200]["y"])
        ref = hex_to_signed32(trace[200]["ref"])
        assert y_200 > ref, \
            f"Step 200: expected overshoot (y={y_200} > ref={ref})"

    def test_overshoot_magnitude(self, trace):
        """Peak overshoot should be between 10% and 60% for zeta=0.3."""
        ref = hex_to_signed32(trace[200]["ref"])
        peak = 0
        for k in range(150, 300):
            y = hex_to_signed32(trace[k]["y"])
            if y > peak:
                peak = y
        overshoot_pct = 100.0 * (peak - ref) / ref
        assert 10.0 < overshoot_pct < 60.0, \
            f"Overshoot {overshoot_pct:.1f}% outside expected range"

    def test_settling_to_reference(self, trace):
        """Output should settle near reference by step 2000."""
        y = hex_to_signed32(trace[2000]["y"])
        ref = hex_to_signed32(trace[2000]["ref"])
        error = abs(y - ref)
        assert error < 655, \
            f"Step 2000: not settled (y={y}, ref={ref}, err={error})"

    def test_step_down_response(self, trace):
        """After step-down at k=3000, output should decrease."""
        y_3000 = hex_to_signed32(trace[3000]["y"])
        y_3100 = hex_to_signed32(trace[3100]["y"])
        assert y_3100 < y_3000, \
            f"Output should decrease after step-down"

    def test_negative_control_during_stepdown(self, trace):
        """Control should go negative to drive output down after step-down."""
        u_3000 = hex_to_signed32(trace[3000]["u"])
        assert u_3000 < 0, \
            f"Step 3000: control should be negative during step-down, got {u_3000}"

    def test_final_tracking(self, trace):
        """Output should track 0.5 reference at end of simulation."""
        y = hex_to_signed32(trace[4999]["y"])
        ref = hex_to_signed32(trace[4999]["ref"])
        error = abs(y - ref)
        assert error < 655, \
            f"Step 4999: not tracking (y={y}, ref={ref}, err={error})"

    def test_output_saturation_respected(self, trace):
        """Control output should never exceed saturation limits."""
        out_max = hex_to_signed32("000a0000")  # 10.0 in Q16.16
        out_min = hex_to_signed32("fff60000")  # -10.0 in Q16.16
        for k in range(5000):
            u = hex_to_signed32(trace[k]["u"])
            assert u <= out_max, \
                f"Step {k}: u={u} exceeds max {out_max}"
            assert u >= out_min, \
                f"Step {k}: u={u} below min {out_min}"

    def test_steady_state_error_decreasing(self, trace):
        """Steady-state error should decrease monotonically after settling."""
        errors = []
        for k in [1500, 1750, 2000, 2250, 2500]:
            e = abs(hex_to_signed32(trace[k]["error"]))
            errors.append(e)
        for i in range(len(errors) - 1):
            assert errors[i] >= errors[i + 1], \
                f"Error not decreasing: {errors}"


class TestGoldenTrace:
    """Exact match against golden reference within Q16.16 tolerance."""

    @pytest.mark.parametrize("step_idx", sorted(GOLDEN.keys()))
    def test_output_matches_golden(self, trace, step_idx):
        """Plant output y[k] must match golden within +-2 LSBs."""
        golden_y = hex_to_signed32(GOLDEN[step_idx]["y"])
        actual_y = hex_to_signed32(trace[step_idx]["y"])
        diff = abs(actual_y - golden_y)
        assert diff <= TOLERANCE, \
            f"Step {step_idx}: y mismatch (golden=0x{GOLDEN[step_idx]['y']}, " \
            f"actual=0x{trace[step_idx]['y']}, diff={diff} LSBs)"

    @pytest.mark.parametrize("step_idx", sorted(GOLDEN.keys()))
    def test_control_matches_golden(self, trace, step_idx):
        """Control output u[k] must match golden within +-2 LSBs."""
        golden_u = hex_to_signed32(GOLDEN[step_idx]["u"])
        actual_u = hex_to_signed32(trace[step_idx]["u"])
        diff = abs(actual_u - golden_u)
        assert diff <= TOLERANCE, \
            f"Step {step_idx}: u mismatch (golden=0x{GOLDEN[step_idx]['u']}, " \
            f"actual=0x{trace[step_idx]['u']}, diff={diff} LSBs)"

    @pytest.mark.parametrize("step_idx", sorted(GOLDEN.keys()))
    def test_error_matches_golden(self, trace, step_idx):
        """Error e[k] must match golden within +-2 LSBs."""
        golden_e = hex_to_signed32(GOLDEN[step_idx]["error"])
        actual_e = hex_to_signed32(trace[step_idx]["error"])
        diff = abs(actual_e - golden_e)
        assert diff <= TOLERANCE, \
            f"Step {step_idx}: error mismatch (golden=0x{GOLDEN[step_idx]['error']}, " \
            f"actual=0x{trace[step_idx]['error']}, diff={diff} LSBs)"


class TestSourceIntegrity:
    """Verify that only pid_controller.c was modified."""

    def _read_file(self, path):
        if not os.path.isfile(path):
            return None
        with open(path) as f:
            return f.read()

    def test_fixpoint_h_unmodified(self):
        content = self._read_file("/app/fixpoint.h")
        assert content is not None, "fixpoint.h missing"
        assert "fix16_smul" in content, "fixpoint.h appears modified"
        assert "FIX16_HALF" in content, "fixpoint.h core content altered"

    def test_plant_c_unmodified(self):
        content = self._read_file("/app/plant.c")
        assert content is not None, "plant.c missing"
        assert "plant_step" in content, "plant.c appears modified"

    def test_sim_harness_unmodified(self):
        content = self._read_file("/app/sim_harness.c")
        assert content is not None, "sim_harness.c missing"
        assert "trace_output.csv" in content, "sim_harness.c appears modified"

    def test_sim_params_unmodified(self):
        content = self._read_file("/app/sim_params.h")
        assert content is not None, "sim_params.h missing"
        assert "SIM_NUM_STEPS" in content, "sim_params.h appears modified"
        assert "5000" in content, "sim_params.h step count altered"

    def test_pid_controller_no_file_io(self):
        """pid_controller.c must not perform file I/O."""
        content = self._read_file("/app/pid_controller.c")
        assert content is not None, "pid_controller.c missing"
        io_patterns = ["fopen", "fread", "fscanf", "fgets",
                        "popen", "system(", "exec"]
        for pat in io_patterns:
            assert pat not in content, \
                f"pid_controller.c must not contain '{pat}'"

    def test_pid_controller_no_stdio_include(self):
        """pid_controller.c should not include stdio."""
        content = self._read_file("/app/pid_controller.c")
        assert content is not None
        assert "#include <stdio.h>" not in content, \
            "pid_controller.c should not include <stdio.h>"
