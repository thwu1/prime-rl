"""
Tests for NEC2 antenna characterization tool.
Validates correct parsing of NEC2 deck and output files,
cross-validation between them, and derived antenna metrics
against known NEC2 validation example data.
"""


import json
import subprocess
import os
import math
import pytest

TOOL = "/app/nec2_char"


def run_tool(deck, output, run_number=1):
    """Run the characterization tool and parse JSON output."""
    result = subprocess.run(
        [TOOL, deck, output, str(run_number)],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"Tool exited {result.returncode}: {result.stderr}"
    data = json.loads(result.stdout)
    return data


class TestCompilation:
    """Verify the tool builds and runs."""

    def test_binary_exists(self):
        assert os.path.isfile(TOOL), "Binary not found at /app/nec2_char"

    def test_runs_on_ex1(self):
        result = subprocess.run(
            [TOOL, "/app/data/dipole.nec", "/app/data/ex1_output.txt"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"Tool crashed: {result.stderr}"

    def test_output_is_json(self):
        result = subprocess.run(
            [TOOL, "/app/data/dipole.nec", "/app/data/ex1_output.txt"],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        assert "deck" in data
        assert "output" in data
        assert "validation" in data


class TestEx1DeckParsing:
    """Test deck parser against dipole.nec (1 wire, 7 segments)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_tool("/app/data/dipole.nec", "/app/data/ex1_output.txt")

    def test_num_wires(self):
        assert self.data["deck"]["num_wires"] == 1

    def test_total_segments(self):
        assert self.data["deck"]["total_segments"] == 7

    def test_frequency(self):
        freq = self.data["deck"]["frequency_mhz"]
        assert freq is not None
        assert freq == pytest.approx(299.8, rel=1e-3)

    def test_excitation_tag(self):
        assert self.data["deck"]["excitation_tag"] == 0

    def test_excitation_seg(self):
        assert self.data["deck"]["excitation_seg"] == 4


class TestEx1OutputParsing:
    """Test output parser against ex1: center-fed dipole in free space.
    Single run, no radiation pattern data."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_tool("/app/data/dipole.nec", "/app/data/ex1_output.txt")
        self.out = self.data["output"]

    def test_frequency(self):
        assert self.out["frequency_mhz"] == pytest.approx(299.8, rel=1e-3)

    def test_impedance_real(self):
        assert self.out["impedance_real"] == pytest.approx(82.6979, rel=1e-3)

    def test_impedance_imag(self):
        assert self.out["impedance_imag"] == pytest.approx(46.306, rel=1e-3)

    def test_vswr(self):
        # VSWR for Z=82.698+j46.306 relative to 50 ohms: |Gamma|=0.4033, VSWR=2.352
        assert self.out["vswr"] == pytest.approx(2.3520, rel=5e-3)

    def test_input_power(self):
        assert self.out["input_power"] == pytest.approx(4.6029e-3, rel=1e-3)

    def test_radiated_power(self):
        assert self.out["radiated_power"] == pytest.approx(4.6029e-3, rel=1e-3)

    def test_efficiency(self):
        assert self.out["efficiency"] == pytest.approx(100.0, abs=0.1)

    def test_max_current_magnitude(self):
        # Center segment (4): I = 9.20585e-3 - j5.15474e-3
        # |I| = sqrt(9.20585e-3^2 + 5.15474e-3^2) = 1.0551e-2
        assert self.out["max_current_mag"] == pytest.approx(1.0551e-2, rel=1e-3)

    def test_no_pattern_data(self):
        assert self.out["max_gain_db"] is None
        assert self.out["max_gain_theta"] is None

    def test_no_hpbw(self):
        assert self.out["hpbw_deg"] is None


class TestEx1Validation:
    """Test cross-validation for dipole deck vs output."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_tool("/app/data/dipole.nec", "/app/data/ex1_output.txt")
        self.val = self.data["validation"]

    def test_segments_match(self):
        assert self.val["segments_match"] is True

    def test_excitation_match(self):
        assert self.val["excitation_match"] is True


class TestEx3DeckParsing:
    """Test deck parser against vertical.nec (1 wire, 9 segments)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_tool("/app/data/vertical.nec", "/app/data/ex3_output.txt", 1)

    def test_num_wires(self):
        assert self.data["deck"]["num_wires"] == 1

    def test_total_segments(self):
        assert self.data["deck"]["total_segments"] == 9

    def test_frequency(self):
        freq = self.data["deck"]["frequency_mhz"]
        assert freq is not None
        assert freq == pytest.approx(30.0, rel=1e-3)

    def test_excitation_tag(self):
        assert self.data["deck"]["excitation_tag"] == 0

    def test_excitation_seg(self):
        assert self.data["deck"]["excitation_seg"] == 5


class TestEx3PerfectGround:
    """Test against NEC2 Example 3 Run 1: vertical antenna over perfect ground.
    Has radiation pattern with peak gain at theta=90 (horizon)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_tool("/app/data/vertical.nec", "/app/data/ex3_output.txt", 1)
        self.out = self.data["output"]

    def test_impedance_real(self):
        assert self.out["impedance_real"] == pytest.approx(106.436, rel=1e-3)

    def test_impedance_imag(self):
        assert self.out["impedance_imag"] == pytest.approx(9.9055, rel=1e-2)

    def test_vswr(self):
        assert self.out["vswr"] == pytest.approx(2.1523, rel=5e-3)

    def test_max_current_magnitude(self):
        # Segment 6: I = 9.0040e-3 - j3.8010e-3
        # |I| = sqrt(9.0040e-3^2 + 3.8010e-3^2) = 9.7734e-3
        assert self.out["max_current_mag"] == pytest.approx(9.7734e-3, rel=1e-3)

    def test_max_gain(self):
        assert self.out["max_gain_db"] == pytest.approx(8.52, abs=0.05)

    def test_max_gain_theta(self):
        assert self.out["max_gain_theta"] == pytest.approx(90.0, abs=0.5)

    def test_avg_power_gain(self):
        assert self.out["avg_power_gain"] == pytest.approx(2.02794, rel=1e-3)

    def test_hpbw(self):
        # Peak at theta=90 (boundary); -3dB crossing near theta=76.3
        # HPBW = 2 * (90 - 76.3) ~ 27.4 degrees
        hpbw = self.out["hpbw_deg"]
        assert hpbw is not None, "HPBW should not be null for pattern data"
        assert hpbw == pytest.approx(27.4, abs=2.0)

    def test_efficiency(self):
        assert self.out["efficiency"] == pytest.approx(100.0, abs=0.1)

    def test_segments_match(self):
        assert self.data["validation"]["segments_match"] is True

    def test_excitation_match(self):
        assert self.data["validation"]["excitation_match"] is True


class TestEx3FiniteGround:
    """Test against NEC2 Example 3 Run 2: vertical antenna over finite ground.
    Has radiation pattern with peak gain at theta=70."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = run_tool("/app/data/vertical.nec", "/app/data/ex3_output.txt", 2)
        self.out = self.data["output"]

    def test_impedance_real(self):
        assert self.out["impedance_real"] == pytest.approx(111.117, rel=1e-3)

    def test_impedance_imag(self):
        assert self.out["impedance_imag"] == pytest.approx(11.0081, rel=1e-2)

    def test_vswr(self):
        assert self.out["vswr"] == pytest.approx(2.2496, rel=5e-3)

    def test_max_current_magnitude(self):
        # Segment 6: I = 8.5576e-3 - j3.8085e-3
        # |I| = sqrt(8.5576e-3^2 + 3.8085e-3^2) = 9.3669e-3
        assert self.out["max_current_mag"] == pytest.approx(9.3669e-3, rel=1e-3)

    def test_max_gain(self):
        assert self.out["max_gain_db"] == pytest.approx(1.54, abs=0.05)

    def test_max_gain_theta(self):
        assert self.out["max_gain_theta"] == pytest.approx(70.0, abs=0.5)

    def test_avg_power_gain(self):
        assert self.out["avg_power_gain"] == pytest.approx(0.720701, rel=1e-3)

    def test_hpbw(self):
        # Peak at theta=70 (interior); lower -3dB crossing near theta=56.9
        # Upper side: 80 deg still above threshold, 90 is sentinel
        # HPBW = 2 * (70 - 56.9) ~ 26.2 degrees
        hpbw = self.out["hpbw_deg"]
        assert hpbw is not None, "HPBW should not be null for pattern data"
        assert hpbw == pytest.approx(26.2, abs=2.0)

    def test_efficiency(self):
        assert self.out["efficiency"] == pytest.approx(100.0, abs=0.1)

    def test_segments_match(self):
        assert self.data["validation"]["segments_match"] is True

    def test_excitation_match(self):
        assert self.data["validation"]["excitation_match"] is True


class TestConsistency:
    """Cross-scenario consistency checks."""

    def test_dipole_impedance_not_current(self):
        """Impedance should be ~82 ohms, not ~0.009 (which is the current)."""
        data = run_tool("/app/data/dipole.nec", "/app/data/ex1_output.txt")
        z_re = data["output"]["impedance_real"]
        assert z_re > 1.0, f"Impedance real={z_re} looks like current, not impedance"

    def test_vertical_impedance_not_current(self):
        """Impedance should be ~106 ohms, not ~0.009."""
        data = run_tool("/app/data/vertical.nec", "/app/data/ex3_output.txt", 1)
        z_re = data["output"]["impedance_real"]
        assert z_re > 1.0, f"Impedance real={z_re} looks like current, not impedance"

    def test_vswr_reasonable_range(self):
        """VSWR should be between 1 and ~10 for these antennas."""
        data = run_tool("/app/data/dipole.nec", "/app/data/ex1_output.txt")
        vswr = data["output"]["vswr"]
        assert 1.0 < vswr < 10.0, f"VSWR={vswr} outside reasonable range"

    def test_current_magnitude_is_l2_norm(self):
        """Max current for dipole: sqrt(0.00921^2 + 0.00515^2) ~ 0.01055,
        NOT fabs(0.00921) + fabs(0.00515) ~ 0.01436."""
        data = run_tool("/app/data/dipole.nec", "/app/data/ex1_output.txt")
        mag = data["output"]["max_current_mag"]
        assert mag < 0.012, f"|I|={mag} suggests L1 norm instead of L2"

    def test_gain_uses_total_column(self):
        """Max gain for perfect-ground vertical should be ~8.5 dBi (total),
        not -999.99 dBi (horizontal, which is zero for this antenna)."""
        data = run_tool("/app/data/vertical.nec", "/app/data/ex3_output.txt", 1)
        g = data["output"]["max_gain_db"]
        assert g is not None
        assert g > 0.0, f"Max gain={g} dB suggests wrong column (horizontal is -999.99)"
