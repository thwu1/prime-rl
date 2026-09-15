
import subprocess
import os
import math
import tempfile
import pytest

CIRCUITS_DIR = "/app/circuits"
SIMULATOR = "/app/acsim.py"

REL_TOL = 1e-3
ABS_TOL = 1e-9


def parse_output(text):
    """Parse simulator tab-separated output."""
    lines = text.strip().split("\n")
    result = []
    header = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            parts = line.split("\t")
            header = [p.strip() for p in parts[1:]]
            continue
        if header is None:
            continue
        parts = line.split("\t")
        freq = float(parts[0])
        values = {}
        for i, h in enumerate(header):
            if i + 1 < len(parts):
                values[h] = float(parts[i + 1])
        result.append((freq, values))
    return header, result


def run_simulator(netlist_path):
    """Run the AC simulator on a netlist and return parsed output."""
    result = subprocess.run(
        ["python3", SIMULATOR, netlist_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Simulator failed with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout[:500]}"
    )
    return parse_output(result.stdout)


def compare_values(actual, expected, label=""):
    """Compare two values within tolerance."""
    if abs(expected) > ABS_TOL:
        rel_err = abs(actual - expected) / abs(expected)
        assert rel_err < REL_TOL, (
            f"{label}: relative error {rel_err:.6e} exceeds {REL_TOL} "
            f"(actual={actual:.6g}, expected={expected:.6g})"
        )
    else:
        assert abs(actual - expected) < ABS_TOL, (
            f"{label}: absolute error {abs(actual - expected):.6e} exceeds {ABS_TOL} "
            f"(actual={actual:.6g}, expected={expected:.6g})"
        )


def write_temp_netlist(text):
    """Write a netlist to a temp file and return the path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".net", delete=False)
    f.write(text)
    f.close()
    return f.name


# ── Basics ────────────────────────────────────────────────────────

class TestSimulatorBasics:
    def test_file_exists(self):
        assert os.path.isfile(SIMULATOR), f"Simulator not found at {SIMULATOR}"

    def test_is_python(self):
        with open(SIMULATOR, "r") as f:
            content = f.read()
        assert "import" in content or "def " in content, (
            "Simulator does not appear to be a Python file"
        )

    def test_standalone_implementation(self):
        """Simulator must not shell out to external tools."""
        with open(SIMULATOR, "r") as f:
            src = f.read()
        for token in ["subprocess", "os.system(", "os.popen(", "Popen",
                       "commands.get"]:
            assert token not in src, (
                f"Simulator must be a standalone implementation (found '{token}')"
            )
        # Must not wrap gnucap
        lines = [l for l in src.split("\n")
                 if not l.strip().startswith("#") and not l.strip().startswith("'")
                 and not l.strip().startswith('"')]
        code_no_comments = "\n".join(lines)
        assert "gnucap" not in code_no_comments.lower(), (
            "Simulator must not invoke gnucap"
        )


# ── Voltage divider (purely resistive) ───────────────────────────

class TestVoltageDivider:
    def test_constant_output(self):
        """R-R voltage divider: V(2) = R2/(R1+R2) = 200/300 at all freq."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "voltage_divider.net"))
        assert len(data) > 0, "No data rows produced"
        for freq, vals in data:
            if "v(2)" in vals:
                compare_values(vals["v(2)"], 200.0 / 300.0, f"f={freq} v(2)")

    def test_source_node_unity(self):
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "voltage_divider.net"))
        for freq, vals in data:
            if "v(1)" in vals:
                compare_values(vals["v(1)"], 1.0, f"f={freq} v(1)")


# ── RC low-pass filter ───────────────────────────────────────────

class TestRCLowpass:
    """V1(1V) -> R(1k) -> node 2 -> C(100n) -> ground."""

    def test_dc_passthrough(self):
        """At DC capacitor is open circuit: V(2) = V(1) = 1."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "rc_lowpass.net"))
        dc = data[0]
        compare_values(dc[1].get("v(2)", 0), 1.0, "DC v(2)")

    def test_rolloff_curve(self):
        """Magnitude must follow 1/sqrt(1 + (wRC)^2)."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "rc_lowpass.net"))
        R, C_val = 1000.0, 100e-9
        for freq, vals in data:
            if freq == 0 or "v(2)" not in vals:
                continue
            w = 2 * math.pi * freq
            expected = 1.0 / math.sqrt(1.0 + (w * R * C_val) ** 2)
            compare_values(vals["v(2)"], expected, f"f={freq}")

    def test_monotonic_decrease(self):
        """Voltage magnitude should decrease with frequency."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "rc_lowpass.net"))
        mags = [vals.get("v(2)", 0) for _, vals in data]
        for i in range(1, len(mags)):
            assert mags[i] <= mags[i - 1] + REL_TOL, (
                f"Not monotonically decreasing at index {i}: "
                f"{mags[i]:.6g} > {mags[i-1]:.6g}"
            )


# ── RL high-pass filter ──────────────────────────────────────────

class TestRLHighpass:
    """V1(1V) -> R(100) -> node 2 -> L(10m) -> ground."""

    def test_dc_zero(self):
        """At DC inductor is short circuit: V(2) = 0."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "rl_highpass.net"))
        dc = data[0]
        assert dc[1].get("v(2)", 1.0) < 1e-3, "V(2) should be ~0 at DC"

    def test_transfer_function(self):
        """Magnitude: wL / sqrt(R^2 + (wL)^2)."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "rl_highpass.net"))
        R, L_val = 100.0, 10e-3
        for freq, vals in data:
            if freq == 0 or "v(2)" not in vals:
                continue
            w = 2 * math.pi * freq
            expected = w * L_val / math.sqrt(R ** 2 + (w * L_val) ** 2)
            compare_values(vals["v(2)"], expected, f"f={freq}")

    def test_monotonic_increase(self):
        """Voltage magnitude should increase with frequency."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "rl_highpass.net"))
        mags = [vals.get("v(2)", 0) for _, vals in data]
        for i in range(1, len(mags)):
            assert mags[i] >= mags[i - 1] - REL_TOL, (
                f"Not monotonically increasing at index {i}: "
                f"{mags[i]:.6g} < {mags[i-1]:.6g}"
            )


# ── Matched transmission line ────────────────────────────────────

class TestMatchedTline:
    def test_constant_half_voltage(self):
        """Matched load (Z0 = R_s = R_l = 50): V = 0.5 at all freq."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "matched_tline.net"))
        assert len(data) > 0
        for freq, vals in data:
            for nd in ["v(11)", "v(12)"]:
                if nd in vals:
                    compare_values(vals[nd], 0.5, f"f={freq} {nd}")

    def test_source_unity(self):
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "matched_tline.net"))
        for freq, vals in data:
            if "v(1)" in vals:
                compare_values(vals["v(1)"], 1.0, f"f={freq} v(1)")


# ── Open stub ─────────────────────────────────────────────────────

class TestOpenStub:
    def test_far_end_voltage_unity(self):
        """Open-end voltage magnitude equals source voltage at all freq."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "open_stub.net"))
        assert len(data) > 0
        for freq, vals in data:
            if "v(22)" in vals:
                compare_values(vals["v(22)"], 1.0, f"f={freq} v(22)")

    def test_input_voltage_pattern(self):
        """Input voltage |V(21)| follows |cos(theta)| envelope."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "open_stub.net"))
        td = 0.25 / 10e6
        for freq, vals in data:
            if freq == 0 or "v(21)" not in vals:
                continue
            theta = 2 * math.pi * freq * td
            expected = abs(math.cos(theta))
            if expected > 0.02:
                compare_values(vals["v(21)"], expected, f"f={freq} v(21)")


# ── Cascaded transmission lines ──────────────────────────────────

class TestCascadedTlines:
    def test_dc_voltage_divider(self):
        """At DC lossless lines act as wires: V = R_l / (R_s + R_l)."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "cascaded_tline.net"))
        dc = data[0]
        for nd in ["v(2)", "v(3)", "v(4)"]:
            if nd in dc[1]:
                compare_values(dc[1][nd], 2.0 / 3.0, f"DC {nd}")

    def test_frequency_symmetry(self):
        """Output should be symmetric around f=20 MHz (full-wave period)."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "cascaded_tline.net"))
        for i in range(min(11, len(data))):
            j = 20 - i  # index symmetric about 20 MHz (idx 10)
            if j >= len(data):
                continue
            for nd in data[i][1]:
                v1 = data[i][1][nd]
                v2 = data[j][1].get(nd, v1)
                if abs(v1) > ABS_TOL:
                    assert abs(v1 - v2) / abs(v1) < REL_TOL, (
                        f"Symmetry: {nd} idx {i}={v1:.6g} vs idx {j}={v2:.6g}"
                    )


# ── Dynamically-generated circuits (anti-cheat) ──────────────────

class TestDynamicCircuits:
    """Circuits created at test time. Not in /app/circuits/."""

    def _run_temp(self, netlist_text):
        path = write_temp_netlist(netlist_text)
        try:
            return run_simulator(path)
        finally:
            os.unlink(path)

    def test_novel_rc(self):
        """RC filter with R=470 C=47n — verify against analytical."""
        R, C_val = 470.0, 47e-9
        _, data = self._run_temp(
            "# generated\nV1 1 0 1\n"
            f"R1 1 2 {R}\nC1 2 0 {C_val}\n"
            ".ac 0 500k 50k\n"
        )
        assert len(data) > 0
        for freq, vals in data:
            if "v(2)" not in vals:
                continue
            if freq == 0:
                compare_values(vals["v(2)"], 1.0, "f=0")
            else:
                w = 2 * math.pi * freq
                expected = 1.0 / math.sqrt(1.0 + (w * R * C_val) ** 2)
                compare_values(vals["v(2)"], expected, f"f={freq}")

    def test_novel_tline(self):
        """Tline with unusual parameters — verify via ABCD analytical."""
        R_s, Z0, f_ref, nl, R_l = 47.0, 83.0, 6.7e6, 0.37, 220.0
        _, data = self._run_temp(
            "# generated\nV1 1 0 1\n"
            f"Rs 1 2 {R_s}\n"
            f"T1 2 0 3 0 z={Z0} f={f_ref} nl={nl}\n"
            f"Rl 3 0 {R_l}\n"
            ".ac 500k 9500k 1meg\n"
        )
        assert len(data) >= 5
        td = nl / f_ref
        for freq, vals in data:
            if freq == 0:
                continue
            theta = 2 * math.pi * freq * td
            cos_t = math.cos(theta)
            sin_t = math.sin(theta)
            tan_t = math.tan(theta)
            # analytical input impedance
            z_in = Z0 * complex(R_l, Z0 * tan_t) / complex(Z0, R_l * tan_t)
            # voltage divider for V(2)
            v_in = z_in / (R_s + z_in)
            # ABCD: V_out = V_in / (cos(theta) + j*Z0/R_l * sin(theta))
            v_out = v_in / complex(cos_t, Z0 / R_l * sin_t)
            if "v(2)" in vals:
                compare_values(vals["v(2)"], abs(v_in), f"f={freq} v(2)")
            if "v(3)" in vals:
                compare_values(vals["v(3)"], abs(v_out), f"f={freq} v(3)")

    def test_novel_rlc_series(self):
        """Series RLC — exercises all reactive element types together."""
        R, L_val, C_val = 150.0, 22e-3, 33e-9
        _, data = self._run_temp(
            "# generated\nV1 1 0 1\n"
            f"R1 1 2 {R}\nL1 2 3 {L_val}\nC1 3 0 {C_val}\n"
            ".ac 0 50k 5k\n"
        )
        assert len(data) > 0
        for freq, vals in data:
            if "v(3)" not in vals:
                continue
            if freq == 0:
                # DC: L short, C open, no current, V3 = V1 = 1
                compare_values(vals["v(3)"], 1.0, "DC v(3)")
            else:
                w = 2 * math.pi * freq
                z_l = complex(0, w * L_val)
                z_c = 1.0 / complex(0, w * C_val)
                v3 = z_c / (R + z_l + z_c)
                compare_values(vals["v(3)"], abs(v3), f"f={freq} v(3)")
            if "v(2)" in vals:
                if freq == 0:
                    compare_values(vals["v(2)"], 1.0, "DC v(2)")
                else:
                    w = 2 * math.pi * freq
                    z_l = complex(0, w * L_val)
                    z_c = 1.0 / complex(0, w * C_val)
                    v2 = (z_l + z_c) / (R + z_l + z_c)
                    compare_values(vals["v(2)"], abs(v2), f"f={freq} v(2)")

    def test_novel_tline_with_cap(self):
        """Tline feeding into capacitive load — tests C+T interaction."""
        R_s, Z0, f_ref, nl, C_l = 50.0, 50.0, 10e6, 0.25, 100e-12
        _, data = self._run_temp(
            "# generated\nV1 1 0 1\n"
            f"Rs 1 2 {R_s}\n"
            f"T1 2 0 3 0 z={Z0} f={f_ref} nl={nl}\n"
            f"Cl 3 0 {C_l}\n"
            ".ac 2meg 38meg 4meg\n"
        )
        assert len(data) >= 5
        td = nl / f_ref
        for freq, vals in data:
            if freq == 0:
                continue
            theta = 2 * math.pi * freq * td
            cos_t = math.cos(theta)
            sin_t = math.sin(theta)
            w = 2 * math.pi * freq
            z_load = 1.0 / complex(0, w * C_l)  # capacitor impedance
            # input impedance of loaded tline
            z_in = Z0 * (z_load + complex(0, Z0 * math.tan(theta))) / (
                complex(Z0, 0) + complex(0, 1) * z_load * math.tan(theta))
            v_in = z_in / (R_s + z_in)
            v_out = v_in / (cos_t + complex(0, Z0) * sin_t / z_load)
            if "v(3)" in vals:
                compare_values(vals["v(3)"], abs(v_out), f"f={freq} v(3)")


# ── Resonance and robustness ─────────────────────────────────────

class TestResonanceHandling:
    def test_no_nan_or_inf(self):
        """Output must never contain NaN or Inf for any provided circuit."""
        for fname in os.listdir(CIRCUITS_DIR):
            if not fname.endswith(".net"):
                continue
            result = subprocess.run(
                ["python3", SIMULATOR, os.path.join(CIRCUITS_DIR, fname)],
                capture_output=True, text=True, timeout=60,
            )
            out = result.stdout.lower()
            assert "nan" not in out, f"{fname}: output contains NaN"
            assert "inf" not in out, f"{fname}: output contains Inf"

    def test_resonance_circuit(self):
        """Quarter-wave and half-wave points must produce finite values."""
        path = write_temp_netlist(
            "# resonance sweep\nV1 1 0 1\nRs 1 2 50\n"
            "T1 2 0 3 0 z=50 f=10meg nl=0.25\nRl 3 0 200\n"
            ".ac 0 40meg 2meg\n"
        )
        try:
            result = subprocess.run(
                ["python3", SIMULATOR, path],
                capture_output=True, text=True, timeout=60,
            )
            out = result.stdout.lower()
            assert "nan" not in out, "NaN at resonance"
            assert "inf" not in out, "Inf at resonance"
            _, data = parse_output(result.stdout)
            assert len(data) == 21, f"Expected 21 freq points, got {len(data)}"
        finally:
            os.unlink(path)


# ── Output format ────────────────────────────────────────────────

class TestOutputFormat:
    def test_header_format(self):
        result = subprocess.run(
            ["python3", SIMULATOR, os.path.join(CIRCUITS_DIR, "voltage_divider.net")],
            capture_output=True, text=True, timeout=60,
        )
        lines = result.stdout.strip().split("\n")
        assert lines[0].startswith("#Freq"), "Header must start with #Freq"
        assert "v(" in lines[0], "Header must contain v(<node>) labels"

    def test_tab_separated_columns(self):
        result = subprocess.run(
            ["python3", SIMULATOR, os.path.join(CIRCUITS_DIR, "voltage_divider.net")],
            capture_output=True, text=True, timeout=60,
        )
        lines = result.stdout.strip().split("\n")
        ncols = len(lines[0].split("\t"))
        for line in lines[1:]:
            if line.strip():
                assert len(line.split("\t")) == ncols, (
                    f"Column count mismatch: {line}"
                )

    def test_nodes_ascending_order(self):
        result = subprocess.run(
            ["python3", SIMULATOR,
             os.path.join(CIRCUITS_DIR, "cascaded_tline.net")],
            capture_output=True, text=True, timeout=60,
        )
        header = result.stdout.strip().split("\n")[0]
        parts = header.split("\t")[1:]
        node_nums = []
        for p in parts:
            p = p.strip()
            num_str = p.replace("v(", "").replace(")", "")
            node_nums.append(int(num_str))
        assert node_nums == sorted(node_nums), (
            f"Node columns not ascending: {node_nums}"
        )

    def test_frequency_count(self):
        """Voltage divider .ac 0 10k 500 should give 21 points."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "voltage_divider.net"))
        assert len(data) == 21, f"Expected 21 freq points, got {len(data)}"


# ── SI suffix parsing ────────────────────────────────────────────

class TestSISuffixes:
    def test_meg_suffix_via_matched(self):
        """10meg in netlist must parse as 1e7."""
        _, data = run_simulator(os.path.join(CIRCUITS_DIR, "matched_tline.net"))
        found = False
        for freq, vals in data:
            if abs(freq - 10e6) < 1:
                found = True
                for nd in vals:
                    if "11" in nd or "12" in nd:
                        compare_values(vals[nd], 0.5, f"10MHz {nd}")
        assert found, "10 MHz frequency point not found"

    def test_various_suffixes(self):
        """Exercise k, m, n, meg suffixes in a single circuit."""
        _, data = self._run_suffix_circuit()
        assert len(data) > 0, "No data from suffix circuit"
        # R=1k=1000, C=100n=1e-7, .ac 0 10k 1k
        R, C_val = 1000.0, 100e-9
        for freq, vals in data:
            if freq == 0 or "v(2)" not in vals:
                continue
            w = 2 * math.pi * freq
            expected = 1.0 / math.sqrt(1.0 + (w * R * C_val) ** 2)
            compare_values(vals["v(2)"], expected, f"f={freq}")

    def _run_suffix_circuit(self):
        path = write_temp_netlist(
            "# suffix test\nV1 1 0 1\nR1 1 2 1k\nC1 2 0 100n\n.ac 0 10k 1k\n"
        )
        try:
            return run_simulator(path)
        finally:
            os.unlink(path)
