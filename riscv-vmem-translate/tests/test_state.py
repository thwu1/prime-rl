
import json
import os
import struct
import subprocess
import pytest


def parse_hex(s):
    """Parse a hex value from int or string."""
    if isinstance(s, int):
        return s
    s = str(s).strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    return int(s, 16)


def norm_hex(v):
    """Normalize to comparable lowercase hex int."""
    return parse_hex(v)


# Expected correct PTE values for each fault, keyed by fault ID.
# offset = byte offset in raw memory (PA - 0x80000000)
# pte_pa = physical address of the broken PTE
# broken = original broken PTE value (for reference)
# fixed  = corrected PTE value
EXPECTED = {
    1:  {"offset": 0x4000, "pte_pa": 0x80004000,
         "broken": 0x0000000020004042, "fixed": 0x0000000020004043},
    2:  {"offset": 0x4008, "pte_pa": 0x80004008,
         "broken": 0x00000000200044C5, "fixed": 0x00000000200044C7},
    3:  {"offset": 0x2008, "pte_pa": 0x80002008,
         "broken": 0x00000000200804CF, "fixed": 0x00000000200800CF},
    4:  {"offset": 0x5000, "pte_pa": 0x80005000,
         "broken": 0x0000000020004843, "fixed": 0x00000000200048C7},
    5:  {"offset": 0x5008, "pte_pa": 0x80005008,
         "broken": 0x0000000020004C03, "fixed": 0x0000000020004C43},
    6:  {"offset": 0x5010, "pte_pa": 0x80005010,
         "broken": 0x0000000020005047, "fixed": 0x00000000200050C7},
    7:  {"offset": 0x6000, "pte_pa": 0x80006000,
         "broken": 0x0000000020005453, "fixed": 0x0000000020005443},
    8:  {"offset": 0x7000, "pte_pa": 0x80007000,
         "broken": 0x0000000020005801, "fixed": 0x0000000020005843},
    9:  {"offset": 0x8000, "pte_pa": 0x80008000,
         "broken": 0x80000000200410C3, "fixed": 0x80000000200420C3},
    10: {"offset": 0x8008, "pte_pa": 0x80008008,
         "broken": 0x0000000020005C43, "fixed": 0x0000000020005C4B},
}

# Non-broken PTEs that must remain unchanged
UNCHANGED_PTES = {
    0x1000: 0x0000000020000801,   # L2[0]
    0x2000: 0x0000000020001001,   # L1[0]
    0x2010: 0x0000000020001401,   # L1[2]
    0x2018: 0x0000000020001801,   # L1[3]
    0x4010: 0x00000000200028C7,   # L0#0[2] valid
    0x4018: 0x000000002000644B,   # L0#0[3] valid
    0x5018: 0x00000000200054CF,   # L0#1[3] valid
    0x6008: 0x0000000020003443,   # L0#2[1] valid
    0x7008: 0x00000000200038C7,   # L0#3[1] valid
    0x8010: 0x0000000020003CCF,   # L0#4[2] valid
}


@pytest.fixture(scope="module")
def diagnosis():
    path = "/app/diagnosis.json"
    assert os.path.exists(path), "diagnosis.json not found"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, list), "diagnosis.json must be a JSON array"
    return {d["id"]: d for d in data}


@pytest.fixture(scope="module")
def fixed_mem():
    qcow2_path = "/app/memory_fixed.qcow2"
    assert os.path.exists(qcow2_path), "memory_fixed.qcow2 not found"
    raw_path = "/tmp/test_memory_fixed.raw"
    result = subprocess.run(
        ["qemu-img", "convert", "-f", "qcow2", "-O", "raw",
         qcow2_path, raw_path],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Failed to convert qcow2 to raw: {result.stderr}"
    with open(raw_path, "rb") as f:
        data = f.read()
    assert len(data) == 256 * 1024, f"memory_fixed must be 256 KiB, got {len(data)}"
    return data


class TestDiagnosisExists:
    def test_file_exists(self):
        assert os.path.exists("/app/diagnosis.json")

    def test_all_faults_present(self, diagnosis):
        for fid in range(1, 11):
            assert fid in diagnosis, f"Missing diagnosis for fault id={fid}"


class TestOutputFormat:
    def test_qcow2_exists(self):
        assert os.path.exists("/app/memory_fixed.qcow2")

    def test_qcow2_format(self):
        result = subprocess.run(
            ["qemu-img", "info", "--output=json", "/app/memory_fixed.qcow2"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, "qemu-img info failed on memory_fixed.qcow2"
        info = json.loads(result.stdout)
        assert info["format"] == "qcow2", f"Output must be qcow2, got {info['format']}"
        assert info["virtual-size"] == 256 * 1024, (
            f"Virtual size must be 256 KiB, got {info['virtual-size']}"
        )


class TestDiagnosisFault1:
    def test_pte_addr(self, diagnosis):
        assert norm_hex(diagnosis[1]["pte_phys_addr"]) == EXPECTED[1]["pte_pa"]

    def test_corrected_pte(self, diagnosis):
        assert norm_hex(diagnosis[1]["corrected_pte"]) == EXPECTED[1]["fixed"]

    def test_has_root_cause(self, diagnosis):
        assert len(str(diagnosis[1].get("root_cause", ""))) > 0


class TestDiagnosisFault2:
    def test_pte_addr(self, diagnosis):
        assert norm_hex(diagnosis[2]["pte_phys_addr"]) == EXPECTED[2]["pte_pa"]

    def test_corrected_pte(self, diagnosis):
        assert norm_hex(diagnosis[2]["corrected_pte"]) == EXPECTED[2]["fixed"]

    def test_has_root_cause(self, diagnosis):
        assert len(str(diagnosis[2].get("root_cause", ""))) > 0


class TestDiagnosisFault3:
    def test_pte_addr(self, diagnosis):
        assert norm_hex(diagnosis[3]["pte_phys_addr"]) == EXPECTED[3]["pte_pa"]

    def test_corrected_pte(self, diagnosis):
        assert norm_hex(diagnosis[3]["corrected_pte"]) == EXPECTED[3]["fixed"]

    def test_has_root_cause(self, diagnosis):
        assert len(str(diagnosis[3].get("root_cause", ""))) > 0


class TestDiagnosisFault4:
    def test_pte_addr(self, diagnosis):
        assert norm_hex(diagnosis[4]["pte_phys_addr"]) == EXPECTED[4]["pte_pa"]

    def test_corrected_pte(self, diagnosis):
        assert norm_hex(diagnosis[4]["corrected_pte"]) == EXPECTED[4]["fixed"]

    def test_has_root_cause(self, diagnosis):
        assert len(str(diagnosis[4].get("root_cause", ""))) > 0


class TestDiagnosisFault5:
    def test_pte_addr(self, diagnosis):
        assert norm_hex(diagnosis[5]["pte_phys_addr"]) == EXPECTED[5]["pte_pa"]

    def test_corrected_pte(self, diagnosis):
        assert norm_hex(diagnosis[5]["corrected_pte"]) == EXPECTED[5]["fixed"]

    def test_has_root_cause(self, diagnosis):
        assert len(str(diagnosis[5].get("root_cause", ""))) > 0


class TestDiagnosisFault6:
    def test_pte_addr(self, diagnosis):
        assert norm_hex(diagnosis[6]["pte_phys_addr"]) == EXPECTED[6]["pte_pa"]

    def test_corrected_pte(self, diagnosis):
        assert norm_hex(diagnosis[6]["corrected_pte"]) == EXPECTED[6]["fixed"]

    def test_has_root_cause(self, diagnosis):
        assert len(str(diagnosis[6].get("root_cause", ""))) > 0


class TestDiagnosisFault7:
    def test_pte_addr(self, diagnosis):
        assert norm_hex(diagnosis[7]["pte_phys_addr"]) == EXPECTED[7]["pte_pa"]

    def test_corrected_pte(self, diagnosis):
        assert norm_hex(diagnosis[7]["corrected_pte"]) == EXPECTED[7]["fixed"]

    def test_has_root_cause(self, diagnosis):
        assert len(str(diagnosis[7].get("root_cause", ""))) > 0


class TestDiagnosisFault8:
    def test_pte_addr(self, diagnosis):
        assert norm_hex(diagnosis[8]["pte_phys_addr"]) == EXPECTED[8]["pte_pa"]

    def test_corrected_pte(self, diagnosis):
        assert norm_hex(diagnosis[8]["corrected_pte"]) == EXPECTED[8]["fixed"]

    def test_has_root_cause(self, diagnosis):
        assert len(str(diagnosis[8].get("root_cause", ""))) > 0


class TestDiagnosisFault9:
    def test_pte_addr(self, diagnosis):
        assert norm_hex(diagnosis[9]["pte_phys_addr"]) == EXPECTED[9]["pte_pa"]

    def test_corrected_pte(self, diagnosis):
        assert norm_hex(diagnosis[9]["corrected_pte"]) == EXPECTED[9]["fixed"]

    def test_has_root_cause(self, diagnosis):
        assert len(str(diagnosis[9].get("root_cause", ""))) > 0


class TestDiagnosisFault10:
    def test_pte_addr(self, diagnosis):
        assert norm_hex(diagnosis[10]["pte_phys_addr"]) == EXPECTED[10]["pte_pa"]

    def test_corrected_pte(self, diagnosis):
        assert norm_hex(diagnosis[10]["corrected_pte"]) == EXPECTED[10]["fixed"]

    def test_has_root_cause(self, diagnosis):
        assert len(str(diagnosis[10].get("root_cause", ""))) > 0


class TestFixedMemoryCorrections:
    """Verify memory_fixed.qcow2 has the correct PTE values at fault offsets."""

    def test_qcow2_exists(self):
        assert os.path.exists("/app/memory_fixed.qcow2")

    def test_fault1_pte(self, fixed_mem):
        val = struct.unpack_from('<Q', fixed_mem, 0x4000)[0]
        assert val == EXPECTED[1]["fixed"], f"Fault 1: got {hex(val)}, want {hex(EXPECTED[1]['fixed'])}"

    def test_fault2_pte(self, fixed_mem):
        val = struct.unpack_from('<Q', fixed_mem, 0x4008)[0]
        assert val == EXPECTED[2]["fixed"], f"Fault 2: got {hex(val)}, want {hex(EXPECTED[2]['fixed'])}"

    def test_fault3_pte(self, fixed_mem):
        val = struct.unpack_from('<Q', fixed_mem, 0x2008)[0]
        assert val == EXPECTED[3]["fixed"], f"Fault 3: got {hex(val)}, want {hex(EXPECTED[3]['fixed'])}"

    def test_fault4_pte(self, fixed_mem):
        val = struct.unpack_from('<Q', fixed_mem, 0x5000)[0]
        assert val == EXPECTED[4]["fixed"], f"Fault 4: got {hex(val)}, want {hex(EXPECTED[4]['fixed'])}"

    def test_fault5_pte(self, fixed_mem):
        val = struct.unpack_from('<Q', fixed_mem, 0x5008)[0]
        assert val == EXPECTED[5]["fixed"], f"Fault 5: got {hex(val)}, want {hex(EXPECTED[5]['fixed'])}"

    def test_fault6_pte(self, fixed_mem):
        val = struct.unpack_from('<Q', fixed_mem, 0x5010)[0]
        assert val == EXPECTED[6]["fixed"], f"Fault 6: got {hex(val)}, want {hex(EXPECTED[6]['fixed'])}"

    def test_fault7_pte(self, fixed_mem):
        val = struct.unpack_from('<Q', fixed_mem, 0x6000)[0]
        assert val == EXPECTED[7]["fixed"], f"Fault 7: got {hex(val)}, want {hex(EXPECTED[7]['fixed'])}"

    def test_fault8_pte(self, fixed_mem):
        val = struct.unpack_from('<Q', fixed_mem, 0x7000)[0]
        assert val == EXPECTED[8]["fixed"], f"Fault 8: got {hex(val)}, want {hex(EXPECTED[8]['fixed'])}"

    def test_fault9_pte(self, fixed_mem):
        val = struct.unpack_from('<Q', fixed_mem, 0x8000)[0]
        assert val == EXPECTED[9]["fixed"], f"Fault 9: got {hex(val)}, want {hex(EXPECTED[9]['fixed'])}"

    def test_fault10_pte(self, fixed_mem):
        val = struct.unpack_from('<Q', fixed_mem, 0x8008)[0]
        assert val == EXPECTED[10]["fixed"], f"Fault 10: got {hex(val)}, want {hex(EXPECTED[10]['fixed'])}"


class TestFixedMemoryPreservation:
    """Verify non-broken PTEs are unchanged in memory_fixed.qcow2."""

    def test_unchanged_ptes(self, fixed_mem):
        for offset, expected_val in UNCHANGED_PTES.items():
            actual = struct.unpack_from('<Q', fixed_mem, offset)[0]
            assert actual == expected_val, (
                f"Non-broken PTE at offset {hex(offset)} was modified: "
                f"got {hex(actual)}, expected {hex(expected_val)}"
            )

    def test_zero_regions_preserved(self, fixed_mem):
        """Spot-check that regions outside page tables remain zero."""
        for offset in [0x0000, 0x0800, 0x3000, 0x9000, 0xA000]:
            val = struct.unpack_from('<Q', fixed_mem, offset)[0]
            assert val == 0, f"Region at offset {hex(offset)} should be zero, got {hex(val)}"
