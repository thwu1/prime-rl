
import subprocess
import json
import os
import pytest

CONFIG_FILE = "/app/configs/func_river_x1_gui.json"
VHDL_FILE = "/app/rtl/river_cfg.vhd"
TOOL = "/app/soc_analyzer.py"


def run_tool(*args):
    """Run the soc_analyzer tool and return parsed JSON output."""
    cmd = ["python3", TOOL] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (
        f"Tool exited with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout)


class TestToolExists:
    def test_tool_file_exists(self):
        assert os.path.exists(TOOL), f"Analyzer tool not found at {TOOL}"

    def test_config_files_exist(self):
        assert os.path.exists(CONFIG_FILE)
        cfg_dir = os.path.dirname(CONFIG_FILE)
        assert os.path.exists(os.path.join(cfg_dir, "common_riscv.json"))
        assert os.path.exists(os.path.join(cfg_dir, "common_soc.json"))

    def test_vhdl_file_exists(self):
        assert os.path.exists(VHDL_FILE)


class TestMemmap:
    def test_returns_list(self):
        result = run_tool("memmap", CONFIG_FILE)
        assert isinstance(result, list)

    def test_device_count(self):
        result = run_tool("memmap", CONFIG_FILE)
        assert len(result) == 20, f"Expected 20 mapped devices, got {len(result)}"

    def test_sorted_by_address(self):
        result = run_tool("memmap", CONFIG_FILE)
        addresses = [int(d["base_address"], 16) for d in result]
        assert addresses == sorted(addresses), "Map entries must be sorted by base_address"

    def test_contains_key_devices(self):
        result = run_tool("memmap", CONFIG_FILE)
        names = [d["name"] for d in result]
        for expected in ["bootrom0", "sram0", "ddr0", "ddr1", "uart0",
                         "dmi0", "plic0", "clint0", "gpio0", "spiflash0"]:
            assert expected in names, f"Device {expected} missing from map"

    def test_rambbl0_not_in_map(self):
        """rambbl0 is defined but NOT in func_river_x1_gui.json MapList."""
        result = run_tool("memmap", CONFIG_FILE)
        names = [d["name"] for d in result]
        assert "rambbl0" not in names, "rambbl0 should not be in memmap (not in MapList)"

    def test_include_processing(self):
        """Devices from common_riscv.json and common_soc.json must be included."""
        result = run_tool("memmap", CONFIG_FILE)
        names = [d["name"] for d in result]
        assert "ddr0" in names, "Include of common_riscv.json failed"
        assert "uart0" in names, "Include of common_soc.json failed"

    def test_bootrom_fields(self):
        result = run_tool("memmap", CONFIG_FILE)
        bootrom = next(d for d in result if d["name"] == "bootrom0")
        assert int(bootrom["base_address"], 16) == 0x10000
        assert int(bootrom["end_address"], 16) == 0x20000
        assert int(bootrom["length"], 16) == 0x10000
        assert bootrom["class"] == "MemorySimClass"
        assert bootrom["bus"] == "axi0"

    def test_ddr0_fields(self):
        result = run_tool("memmap", CONFIG_FILE)
        ddr0 = next(d for d in result if d["name"] == "ddr0")
        assert int(ddr0["base_address"], 16) == 0x80000000
        assert int(ddr0["length"], 16) == 0x80000000
        assert ddr0["class"] == "DDRClass"

    def test_dmi0_decimal_length(self):
        """dmi0 has Length=4096 (decimal), must be correctly parsed."""
        result = run_tool("memmap", CONFIG_FILE)
        dmi0 = next(d for d in result if d["name"] == "dmi0")
        assert int(dmi0["base_address"], 16) == 0x1000
        assert int(dmi0["length"], 16) == 0x1000  # 4096 decimal = 0x1000

    def test_hex_format(self):
        result = run_tool("memmap", CONFIG_FILE)
        for entry in result:
            for field in ["base_address", "end_address", "length"]:
                val = entry[field]
                assert isinstance(val, str), f"{field} must be a string"
                assert val.startswith("0x"), f"{field} must start with 0x"
                int(val, 16)

    def test_first_device_is_dmi0(self):
        result = run_tool("memmap", CONFIG_FILE)
        assert result[0]["name"] == "dmi0"
        assert int(result[0]["base_address"], 16) == 0x1000

    def test_last_device_is_ddr1(self):
        result = run_tool("memmap", CONFIG_FILE)
        assert result[-1]["name"] == "ddr1"
        assert int(result[-1]["base_address"], 16) == 0x100000000


class TestResolve:
    def test_dmi0_start(self):
        result = run_tool("resolve", CONFIG_FILE, "0x1000")
        assert result["device"] == "dmi0"
        assert int(result["offset"], 16) == 0x0

    def test_bootrom_start(self):
        result = run_tool("resolve", CONFIG_FILE, "0x10000")
        assert result["device"] == "bootrom0"
        assert int(result["offset"], 16) == 0x0
        assert result["read_only"] is True

    def test_bootrom_last_byte(self):
        result = run_tool("resolve", CONFIG_FILE, "0x1FFFF")
        assert result["device"] == "bootrom0"
        assert int(result["offset"], 16) == 0xFFFF

    def test_clint0(self):
        result = run_tool("resolve", CONFIG_FILE, "0x02000000")
        assert result["device"] == "clint0"
        assert int(result["offset"], 16) == 0x0

    def test_sram0(self):
        result = run_tool("resolve", CONFIG_FILE, "0x08000000")
        assert result["device"] == "sram0"
        assert int(result["offset"], 16) == 0x0

    def test_plic0(self):
        result = run_tool("resolve", CONFIG_FILE, "0x0C000000")
        assert result["device"] == "plic0"
        assert int(result["offset"], 16) == 0x0

    def test_uart0(self):
        result = run_tool("resolve", CONFIG_FILE, "0x10010000")
        assert result["device"] == "uart0"
        assert int(result["offset"], 16) == 0x0

    def test_gpio0(self):
        result = run_tool("resolve", CONFIG_FILE, "0x10012000")
        assert result["device"] == "gpio0"
        assert int(result["offset"], 16) == 0x0

    def test_spiflash0(self):
        result = run_tool("resolve", CONFIG_FILE, "0x20000000")
        assert result["device"] == "spiflash0"
        assert int(result["offset"], 16) == 0x0

    def test_ddr0(self):
        """ddr0 at 0x80000000 — rambbl0 is NOT in MapList so no priority override."""
        result = run_tool("resolve", CONFIG_FILE, "0x80000000")
        assert result["device"] == "ddr0"
        assert int(result["offset"], 16) == 0x0

    def test_ddr0_interior(self):
        result = run_tool("resolve", CONFIG_FILE, "0x80800000")
        assert result["device"] == "ddr0"
        assert int(result["offset"], 16) == 0x800000

    def test_ddr1(self):
        result = run_tool("resolve", CONFIG_FILE, "0x100000000")
        assert result["device"] == "ddr1"
        assert int(result["offset"], 16) == 0x0

    def test_unmapped_zero(self):
        result = run_tool("resolve", CONFIG_FILE, "0x0")
        assert result["device"] is None

    def test_unmapped_gap(self):
        """Address between dmi0 end and bootrom0 start."""
        result = run_tool("resolve", CONFIG_FILE, "0x5000")
        assert result["device"] is None

    def test_out_of_range(self):
        """Address beyond 39-bit bus width (>= 0x8000000000)."""
        result = run_tool("resolve", CONFIG_FILE, "0x8000000000")
        assert result["device"] is None
        assert "error" in result
        assert result["error"] == "address_out_of_range"


class TestCrosscheck:
    @pytest.fixture(scope="class")
    def crosscheck_result(self):
        return run_tool("crosscheck", CONFIG_FILE, VHDL_FILE)

    def test_has_checks_array(self, crosscheck_result):
        assert "checks" in crosscheck_result
        assert isinstance(crosscheck_result["checks"], list)

    def test_has_summary(self, crosscheck_result):
        assert "summary" in crosscheck_result
        summary = crosscheck_result["summary"]
        assert "total" in summary
        assert "matches" in summary
        assert "mismatches" in summary

    def test_check_count(self, crosscheck_result):
        assert len(crosscheck_result["checks"]) == 7
        assert crosscheck_result["summary"]["total"] == 7

    def test_summary_counts(self, crosscheck_result):
        summary = crosscheck_result["summary"]
        assert summary["matches"] == 3
        assert summary["mismatches"] == 4

    def _get_check(self, crosscheck_result, param_name):
        for check in crosscheck_result["checks"]:
            if check["parameter"] == param_name:
                return check
        pytest.fail(f"Check '{param_name}' not found in crosscheck output")

    def test_vendor_id_match(self, crosscheck_result):
        check = self._get_check(crosscheck_result, "vendor_id")
        assert check["status"] == "match"

    def test_implementation_id_mismatch(self, crosscheck_result):
        """JSON has 0x20211219, VHDL has 0x20200906."""
        check = self._get_check(crosscheck_result, "implementation_id")
        assert check["status"] == "mismatch"

    def test_fpu_enabled_match(self, crosscheck_result):
        """Both JSON (has 'D' ext) and VHDL (CFG_HW_FPU_ENABLE=true) indicate FPU."""
        check = self._get_check(crosscheck_result, "fpu_enabled")
        assert check["status"] == "match"

    def test_progbuf_total_match(self, crosscheck_result):
        """Both JSON dmi0 and VHDL have ProgbufTotal=16."""
        check = self._get_check(crosscheck_result, "progbuf_total")
        assert check["status"] == "match"

    def test_data_reg_total_mismatch(self, crosscheck_result):
        """JSON dmi0 DataregTotal=6, VHDL CFG_DATA_REG_TOTAL=2."""
        check = self._get_check(crosscheck_result, "data_reg_total")
        assert check["status"] == "mismatch"

    def test_stack_trace_size_mismatch(self, crosscheck_result):
        """JSON core0 StackTraceSize=64, VHDL 2^CFG_LOG2_STACK_TRACE_ADDR=32."""
        check = self._get_check(crosscheck_result, "stack_trace_size")
        assert check["status"] == "mismatch"

    def test_reset_vector_mismatch(self, crosscheck_result):
        """JSON core0 ResetVector=0x10000, VHDL CFG_NMI_RESET_VECTOR=0x00000000."""
        check = self._get_check(crosscheck_result, "reset_vector")
        assert check["status"] == "mismatch"

    def test_all_checks_have_required_fields(self, crosscheck_result):
        for check in crosscheck_result["checks"]:
            assert "parameter" in check
            assert "json_value" in check
            assert "vhdl_value" in check
            assert "status" in check
            assert check["status"] in ("match", "mismatch")
