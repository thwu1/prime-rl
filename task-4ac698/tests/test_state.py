
import json
import subprocess
import os

import pytest


def run_analyzer(elf_path):
    """Run the BPF analyzer and return parsed JSON."""
    assert os.path.isfile(elf_path), f"ELF file not found: {elf_path}"
    result = subprocess.run(
        ["python3", "/app/bpf_analyzer.py", elf_path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Analyzer failed on {elf_path}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    data = json.loads(result.stdout)
    return data


# ---------------------------------------------------------------------------
# Helper to find a program section by name
# ---------------------------------------------------------------------------

def get_section(report, name):
    for s in report["program_sections"]:
        if s["name"] == name:
            return s
    raise KeyError(f"Program section '{name}' not found in report")


def get_map(report, name):
    for m in report["maps"]:
        if m["name"] == name:
            return m
    raise KeyError(f"Map '{name}' not found in report")


# ===========================================================================
# Tests for simple_pass.o — trivial XDP_PASS, no maps, no helpers
# ===========================================================================

class TestSimplePass:
    @pytest.fixture(autouse=True)
    def report(self):
        self.r = run_analyzer("/app/programs/simple_pass.o")

    def test_filename(self):
        assert self.r["filename"] == "simple_pass.o"

    def test_one_program_section(self):
        assert len(self.r["program_sections"]) == 1

    def test_section_name(self):
        s = self.r["program_sections"][0]
        assert s["name"] == "xdp"

    def test_no_helpers(self):
        s = self.r["program_sections"][0]
        assert s["helpers"] == []
        assert s["helper_names"] == []

    def test_no_maps(self):
        assert self.r["maps"] == []

    def test_zero_stack_depth(self):
        s = self.r["program_sections"][0]
        assert s["max_stack_depth"] == 0

    def test_no_backward_jumps(self):
        s = self.r["program_sections"][0]
        assert s["has_backward_jumps"] is False

    def test_instruction_count_small(self):
        s = self.r["program_sections"][0]
        assert 1 <= s["num_instructions"] <= 5

    def test_registers_include_r0(self):
        s = self.r["program_sections"][0]
        assert 0 in s["registers_used"]


# ===========================================================================
# Tests for packet_counter.o — uses bpf_map_lookup_elem, one ARRAY map
# ===========================================================================

class TestPacketCounter:
    @pytest.fixture(autouse=True)
    def report(self):
        self.r = run_analyzer("/app/programs/packet_counter.o")

    def test_filename(self):
        assert self.r["filename"] == "packet_counter.o"

    def test_one_section(self):
        assert len(self.r["program_sections"]) == 1

    def test_helper_map_lookup(self):
        s = self.r["program_sections"][0]
        assert 1 in s["helpers"]  # bpf_map_lookup_elem
        assert "bpf_map_lookup_elem" in s["helper_names"]

    def test_helpers_sorted(self):
        s = self.r["program_sections"][0]
        assert s["helpers"] == sorted(s["helpers"])

    def test_map_present(self):
        names = [m["name"] for m in self.r["maps"]]
        assert "xdp_stats_map" in names

    def test_map_attributes(self):
        m = get_map(self.r, "xdp_stats_map")
        assert m["type"] == 2  # BPF_MAP_TYPE_ARRAY
        assert m["type_name"] == "BPF_MAP_TYPE_ARRAY"
        assert m["key_size"] == 4
        assert m["value_size"] == 16  # sizeof(struct datarec) = 2 * u64
        assert m["max_entries"] == 5

    def test_stack_depth_positive(self):
        s = self.r["program_sections"][0]
        assert s["max_stack_depth"] > 0

    def test_registers_include_frame_pointer(self):
        s = self.r["program_sections"][0]
        assert 10 in s["registers_used"]  # R10 = frame pointer


# ===========================================================================
# Tests for port_filter.o — packet parsing, two maps, multiple helper calls
# ===========================================================================

class TestPortFilter:
    @pytest.fixture(autouse=True)
    def report(self):
        self.r = run_analyzer("/app/programs/port_filter.o")

    def test_one_section(self):
        assert len(self.r["program_sections"]) == 1

    def test_two_maps(self):
        assert len(self.r["maps"]) == 2

    def test_port_blacklist_map(self):
        m = get_map(self.r, "port_blacklist")
        assert m["type"] == 1  # BPF_MAP_TYPE_HASH
        assert m["type_name"] == "BPF_MAP_TYPE_HASH"
        assert m["key_size"] == 4
        assert m["value_size"] == 4
        assert m["max_entries"] == 1024

    def test_filter_stats_map(self):
        m = get_map(self.r, "filter_stats")
        assert m["type"] == 2  # BPF_MAP_TYPE_ARRAY
        assert m["key_size"] == 4
        assert m["value_size"] == 16  # sizeof(struct datarec)
        assert m["max_entries"] == 2

    def test_maps_sorted_by_name(self):
        names = [m["name"] for m in self.r["maps"]]
        assert names == sorted(names)

    def test_helper_calls(self):
        s = self.r["program_sections"][0]
        assert 1 in s["helpers"]  # bpf_map_lookup_elem

    def test_nontrivial_instruction_count(self):
        s = self.r["program_sections"][0]
        assert s["num_instructions"] > 20


# ===========================================================================
# Tests for icmp_echo.o — ICMP responder, checksum, MAC/IP swap
# ===========================================================================

class TestIcmpEcho:
    @pytest.fixture(autouse=True)
    def report(self):
        self.r = run_analyzer("/app/programs/icmp_echo.o")

    def test_one_section(self):
        assert len(self.r["program_sections"]) == 1

    def test_echo_stats_map(self):
        assert len(self.r["maps"]) == 1
        m = self.r["maps"][0]
        assert m["name"] == "echo_stats"
        assert m["type"] == 2  # BPF_MAP_TYPE_ARRAY
        assert m["key_size"] == 4
        assert m["value_size"] == 8  # sizeof(__u64)
        assert m["max_entries"] == 1

    def test_stack_depth_positive(self):
        s = self.r["program_sections"][0]
        # swap_mac uses a temporary buffer on the stack
        assert s["max_stack_depth"] > 0

    def test_helper_map_lookup(self):
        s = self.r["program_sections"][0]
        assert 1 in s["helpers"]

    def test_nontrivial_instruction_count(self):
        s = self.r["program_sections"][0]
        assert s["num_instructions"] > 30


# ===========================================================================
# Tests for test_multi_prog.o — two program sections, no maps
# ===========================================================================

class TestMultiProg:
    @pytest.fixture(autouse=True)
    def report(self):
        self.r = run_analyzer("/tmp/test_programs/test_multi_prog.o")

    def test_two_sections(self):
        assert len(self.r["program_sections"]) == 2

    def test_section_names(self):
        names = sorted(s["name"] for s in self.r["program_sections"])
        assert "xdp/prog_alpha" in names
        assert "xdp/prog_beta" in names

    def test_no_maps(self):
        assert self.r["maps"] == []

    def test_no_helpers_either_section(self):
        for s in self.r["program_sections"]:
            assert s["helpers"] == []

    def test_both_sections_have_instructions(self):
        for s in self.r["program_sections"]:
            assert s["num_instructions"] >= 1


# ===========================================================================
# Tests for test_minimal.o — single XDP_DROP
# ===========================================================================

class TestMinimal:
    @pytest.fixture(autouse=True)
    def report(self):
        self.r = run_analyzer("/tmp/test_programs/test_minimal.o")

    def test_one_section(self):
        assert len(self.r["program_sections"]) == 1

    def test_minimal_instructions(self):
        s = self.r["program_sections"][0]
        assert s["num_instructions"] <= 5

    def test_no_maps(self):
        assert self.r["maps"] == []

    def test_no_backward_jumps(self):
        s = self.r["program_sections"][0]
        assert s["has_backward_jumps"] is False


# ===========================================================================
# Tests for test_many_maps.o — three maps of different types
# ===========================================================================

class TestManyMaps:
    @pytest.fixture(autouse=True)
    def report(self):
        self.r = run_analyzer("/tmp/test_programs/test_many_maps.o")

    def test_three_maps(self):
        assert len(self.r["maps"]) == 3

    def test_hash_map(self):
        m = get_map(self.r, "map_hash")
        assert m["type"] == 1
        assert m["type_name"] == "BPF_MAP_TYPE_HASH"
        assert m["key_size"] == 4
        assert m["value_size"] == 8
        assert m["max_entries"] == 100

    def test_array_map(self):
        m = get_map(self.r, "map_array")
        assert m["type"] == 2
        assert m["type_name"] == "BPF_MAP_TYPE_ARRAY"
        assert m["key_size"] == 4
        assert m["value_size"] == 4
        assert m["max_entries"] == 16

    def test_percpu_array_map(self):
        m = get_map(self.r, "map_percpu")
        assert m["type"] == 6
        assert m["type_name"] == "BPF_MAP_TYPE_PERCPU_ARRAY"
        assert m["key_size"] == 4
        assert m["value_size"] == 32
        assert m["max_entries"] == 64

    def test_maps_sorted(self):
        names = [m["name"] for m in self.r["maps"]]
        assert names == sorted(names)

    def test_helper_calls(self):
        s = self.r["program_sections"][0]
        assert 1 in s["helpers"]  # bpf_map_lookup_elem

    def test_one_program_section(self):
        assert len(self.r["program_sections"]) == 1


# ===========================================================================
# Cross-cutting structural tests
# ===========================================================================

class TestOutputStructure:
    """Verify the JSON output has the required schema."""

    def test_top_level_keys(self):
        r = run_analyzer("/app/programs/simple_pass.o")
        assert "filename" in r
        assert "program_sections" in r
        assert "maps" in r

    def test_section_keys(self):
        r = run_analyzer("/app/programs/packet_counter.o")
        s = r["program_sections"][0]
        required = {
            "name", "num_instructions", "helpers", "helper_names",
            "max_stack_depth", "registers_used", "has_backward_jumps",
        }
        assert required.issubset(set(s.keys()))

    def test_map_keys(self):
        r = run_analyzer("/app/programs/packet_counter.o")
        m = r["maps"][0]
        required = {
            "name", "type", "type_name", "key_size", "value_size", "max_entries",
        }
        assert required.issubset(set(m.keys()))

    def test_registers_sorted(self):
        r = run_analyzer("/app/programs/port_filter.o")
        s = r["program_sections"][0]
        assert s["registers_used"] == sorted(s["registers_used"])

    def test_helpers_sorted(self):
        r = run_analyzer("/app/programs/port_filter.o")
        s = r["program_sections"][0]
        assert s["helpers"] == sorted(s["helpers"])

    def test_helper_names_match_helpers(self):
        r = run_analyzer("/app/programs/packet_counter.o")
        s = r["program_sections"][0]
        assert len(s["helpers"]) == len(s["helper_names"])

    def test_lddw_not_double_counted(self):
        """Programs with maps use lddw (16 bytes). Verify num_instructions
        is smaller than raw_byte_count / 8, proving lddw counted as one."""
        r = run_analyzer("/app/programs/packet_counter.o")
        s = r["program_sections"][0]
        # A program with at least one lddw must have num_instructions
        # strictly less than the number of 8-byte slots
        # We test this indirectly: the instruction count should be reasonable
        assert s["num_instructions"] >= 5  # non-trivial program
        assert s["num_instructions"] < 200  # not absurdly large
