"""Tests for hardware CRC module simulation.

"""

import json
import os
import sys
import random
import importlib

import pytest

# CRC algorithm parameters (integer values matching spec.json)
SPEC = {
    "crc_width": 16,
    "polynomial": 0x755B,
    "initial_crc": 0xC3A5,
    "reflect_input": True,
    "reflect_output": False,
    "xor_output": 0x29B1,
    "data_width": 8,
}


def _get_amaranth_ref():
    """Get reference CRC parameters from Amaranth HDL library."""
    from amaranth.lib.crc import Algorithm

    algo = Algorithm(
        crc_width=SPEC["crc_width"],
        polynomial=SPEC["polynomial"],
        initial_crc=SPEC["initial_crc"],
        reflect_input=SPEC["reflect_input"],
        reflect_output=SPEC["reflect_output"],
        xor_output=SPEC["xor_output"],
    )
    return algo(SPEC["data_width"])


def _get_test_vector_data(tv_id):
    """Generate data for a test vector by ID."""
    mapping = {
        "tv1": [0x00],
        "tv2": [0xFF],
        "tv3": list(b"Hello, World!"),
        "tv4": list(range(256)),
        "tv5": [0xAA] * 128,
    }
    return mapping[tv_id]


def _try_import_module():
    """Import the agent's crc_module."""
    sys.path.insert(0, "/app")
    return importlib.import_module("crc_module")


def _simulate_crc(proc, data):
    """Run Amaranth simulation of a CRCProcessor and return the CRC output."""
    from amaranth.sim import Simulator

    result = {}

    async def testbench(ctx):
        if not data:
            await ctx.tick()
            result["crc"] = ctx.get(proc.crc)
            return

        # Assert start with first data byte
        ctx.set(proc.start, 1)
        ctx.set(proc.data, data[0])
        ctx.set(proc.valid, 1)
        await ctx.tick()

        # Process remaining bytes
        ctx.set(proc.start, 0)
        for byte in data[1:]:
            ctx.set(proc.data, byte)
            await ctx.tick()

        # Deassert valid, allow one cycle for output to settle
        ctx.set(proc.valid, 0)
        await ctx.tick()
        result["crc"] = ctx.get(proc.crc)

    sim = Simulator(proc)
    sim.add_clock(1e-6)
    sim.add_testbench(testbench)
    sim.run()

    return result["crc"]


# ---------------------------------------------------------------------------
# Hardware Module Tests — verify the Elaboratable works in simulation
# ---------------------------------------------------------------------------
class TestHardwareModule:
    def test_is_elaboratable(self):
        """CRCProcessor must be an Amaranth Elaboratable."""
        engine = _try_import_module()
        from amaranth.hdl import Elaboratable

        proc = engine.CRCProcessor(SPEC)
        assert isinstance(proc, Elaboratable), \
            "CRCProcessor must be an Amaranth Elaboratable"

    def test_has_required_signals(self):
        """CRCProcessor must expose start, data, valid, crc attributes."""
        engine = _try_import_module()
        proc = engine.CRCProcessor(SPEC)
        for attr in ("start", "data", "valid", "crc"):
            assert hasattr(proc, attr), \
                f"CRCProcessor missing '{attr}' signal attribute"

    def test_simulate_hello(self):
        """Simulate CRC of 'Hello, World!' through hardware."""
        engine = _try_import_module()
        ref = _get_amaranth_ref()
        data = list(b"Hello, World!")
        expected = ref.compute(data)
        proc = engine.CRCProcessor(SPEC)
        actual = _simulate_crc(proc, data)
        assert actual == expected, \
            f"Hardware CRC of 'Hello, World!': got {actual:#06x}, expected {expected:#06x}"

    def test_simulate_single_byte(self):
        """Simulate CRC of a single byte through hardware."""
        engine = _try_import_module()
        ref = _get_amaranth_ref()
        data = [0x42]
        expected = ref.compute(data)
        proc = engine.CRCProcessor(SPEC)
        actual = _simulate_crc(proc, data)
        assert actual == expected, \
            f"Hardware CRC of [0x42]: got {actual:#06x}, expected {expected:#06x}"

    def test_simulate_random_data(self):
        """Anti-cheat: simulate hardware CRC with pseudo-random data."""
        engine = _try_import_module()
        ref = _get_amaranth_ref()
        rng = random.Random(54321)
        data = [rng.randint(0, 255) for _ in range(200)]
        expected = ref.compute(data)
        proc = engine.CRCProcessor(SPEC)
        actual = _simulate_crc(proc, data)
        assert actual == expected, \
            f"Hardware CRC of random data: got {actual:#06x}, expected {expected:#06x}"


# ---------------------------------------------------------------------------
# Output CRC Value Tests
# ---------------------------------------------------------------------------
class TestOutputCRCValues:
    def test_file_exists(self):
        assert os.path.isfile("/app/output/crc_values.json"), \
            "CRC values output file not found"

    @pytest.mark.parametrize("tv_id", ["tv1", "tv2", "tv3", "tv4", "tv5"])
    def test_crc_value(self, tv_id):
        ref = _get_amaranth_ref()
        data = _get_test_vector_data(tv_id)
        expected = ref.compute(data)

        with open("/app/output/crc_values.json") as f:
            values = json.load(f)
        assert tv_id in values, f"Missing test vector {tv_id}"
        assert values[tv_id] == expected, \
            f"{tv_id}: got {values[tv_id]:#06x}, expected {expected:#06x}"


# ---------------------------------------------------------------------------
# Output Matrix Tests
# ---------------------------------------------------------------------------
class TestOutputMatrices:
    def test_f_matrix_file_exists(self):
        assert os.path.isfile("/app/output/f_matrix.json")

    def test_g_matrix_file_exists(self):
        assert os.path.isfile("/app/output/g_matrix.json")

    def test_f_matrix_dimensions(self):
        with open("/app/output/f_matrix.json") as f:
            fm = json.load(f)
        assert len(fm) == SPEC["crc_width"], \
            f"F matrix should have {SPEC['crc_width']} rows"
        for i, row in enumerate(fm):
            assert len(row) == SPEC["crc_width"], \
                f"F matrix row {i} should have {SPEC['crc_width']} cols"

    def test_g_matrix_dimensions(self):
        with open("/app/output/g_matrix.json") as f:
            gm = json.load(f)
        assert len(gm) == SPEC["data_width"], \
            f"G matrix should have {SPEC['data_width']} rows"
        for i, row in enumerate(gm):
            assert len(row) == SPEC["crc_width"], \
                f"G matrix row {i} should have {SPEC['crc_width']} cols"

    def test_f_matrix_values(self):
        ref = _get_amaranth_ref()
        f_ref, _ = ref._matrices()
        with open("/app/output/f_matrix.json") as f:
            f_agent = json.load(f)
        assert f_agent == f_ref, "F matrix does not match reference"

    def test_g_matrix_values(self):
        ref = _get_amaranth_ref()
        _, g_ref = ref._matrices()
        with open("/app/output/g_matrix.json") as f:
            g_agent = json.load(f)
        assert g_agent == g_ref, "G matrix does not match reference"


# ---------------------------------------------------------------------------
# Output Composition Tests
# ---------------------------------------------------------------------------
class TestOutputComposition:
    def test_file_exists(self):
        assert os.path.isfile("/app/output/composed_crcs.json")

    @pytest.mark.parametrize("comp_id,tv_source", [
        ("comp1", "tv3"),
        ("comp2", "tv4"),
        ("comp3", "tv5"),
    ])
    def test_composed_value(self, comp_id, tv_source):
        ref = _get_amaranth_ref()
        data = _get_test_vector_data(tv_source)
        expected = ref.compute(data)

        with open("/app/output/composed_crcs.json") as f:
            values = json.load(f)
        assert comp_id in values, f"Missing {comp_id}"
        assert values[comp_id] == expected, \
            f"{comp_id}: got {values[comp_id]:#06x}, expected {expected:#06x}"


# ---------------------------------------------------------------------------
# Output Residue Test
# ---------------------------------------------------------------------------
class TestOutputResidue:
    def test_file_exists(self):
        assert os.path.isfile("/app/output/residue.txt")

    def test_residue_value(self):
        ref = _get_amaranth_ref()
        expected = ref.residue()
        with open("/app/output/residue.txt") as f:
            actual = int(f.read().strip())
        assert actual == expected, \
            f"Residue: got {actual:#06x}, expected {expected:#06x}"


# ---------------------------------------------------------------------------
# Function-level anti-cheat tests
# ---------------------------------------------------------------------------
class TestComposeCRCFunction:
    def test_compose_random_data(self):
        """Anti-cheat: test compose_crc with random data and split point."""
        engine = _try_import_module()
        ref = _get_amaranth_ref()

        rng = random.Random(67890)
        data = [rng.randint(0, 255) for _ in range(500)]
        split = 200

        expected = ref.compute(data)
        crc_a = ref.compute(data[:split])
        actual = engine.compose_crc(crc_a, data[split:], SPEC)
        assert actual == expected, \
            f"compose_crc random: got {actual:#06x}, expected {expected:#06x}"

    def test_compose_single_suffix_byte(self):
        """Compose where suffix is a single byte."""
        engine = _try_import_module()
        ref = _get_amaranth_ref()

        data = list(range(50))
        crc_a = ref.compute(data[:49])
        expected = ref.compute(data)
        actual = engine.compose_crc(crc_a, data[49:], SPEC)
        assert actual == expected

    def test_compose_empty_suffix(self):
        """Compose with empty suffix returns original CRC."""
        engine = _try_import_module()
        ref = _get_amaranth_ref()

        data = list(range(100))
        crc_a = ref.compute(data)
        actual = engine.compose_crc(crc_a, [], SPEC)
        assert actual == crc_a


class TestResidueFunction:
    def test_compute_residue(self):
        engine = _try_import_module()
        ref = _get_amaranth_ref()
        expected = ref.residue()
        actual = engine.compute_residue(SPEC)
        assert actual == expected, \
            f"compute_residue: got {actual:#06x}, expected {expected:#06x}"


# ---------------------------------------------------------------------------
# VCD Waveform Validation
# ---------------------------------------------------------------------------
class TestVCDWaveform:
    def test_vcd_file_exists(self):
        assert os.path.isfile("/app/output/hw_simulation.vcd"), \
            "VCD waveform file not found"

    def test_vcd_has_content(self):
        size = os.path.getsize("/app/output/hw_simulation.vcd")
        assert size > 100, f"VCD file too small ({size} bytes), simulation likely did not run"

    def test_vcd_has_signal_definitions(self):
        with open("/app/output/hw_simulation.vcd") as f:
            content = f.read(4096)  # Read first 4K only
        assert "$var" in content, "VCD file missing signal variable definitions"
        assert "$end" in content, "VCD file missing $end markers"
