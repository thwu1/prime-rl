
import json
import os
import subprocess
import pytest


class TestSlangInstallation:
    """Verify that the slang compiler is installed and functional."""

    def test_slang_binary_exists(self):
        result = subprocess.run(
            ["bash", "-c",
             "command -v slang || test -x /usr/local/bin/slang || test -x /usr/bin/slang || find /app -name slang -type f -executable 2>/dev/null | head -1"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, "slang binary not found"

    def test_slang_version(self):
        find_result = subprocess.run(
            ["bash", "-c",
             "command -v slang || find /app /usr/local /opt -name slang -type f -executable 2>/dev/null | head -1"],
            capture_output=True, text=True, timeout=30
        )
        slang_path = find_result.stdout.strip().split('\n')[0]
        if not slang_path:
            pytest.fail("slang binary not found anywhere")
        result = subprocess.run(
            [slang_path, "--version"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"slang --version failed: {result.stderr}"


def _find_slang():
    result = subprocess.run(
        ["bash", "-c",
         "command -v slang || find /app /usr/local /opt -name slang -type f -executable 2>/dev/null | head -1"],
        capture_output=True, text=True, timeout=30
    )
    path = result.stdout.strip().split('\n')[0]
    assert path, "slang binary not found"
    return path


class TestCommandFile:
    """Verify the command file exists and compiles the design."""

    def test_compile_f_exists(self):
        assert os.path.isfile("/app/compile.f"), "/app/compile.f not found"

    def test_compile_f_has_include_path(self):
        with open("/app/compile.f") as f:
            content = f.read()
        has_incdir = (
            "+incdir+" in content
            or "-I" in content
            or "--include-directory" in content
        )
        assert has_incdir, "compile.f missing include directory configuration"

    def test_compile_f_has_library_config(self):
        with open("/app/compile.f") as f:
            content = f.read()
        has_libdir = ("-y" in content or "--libdir" in content)
        has_libext = ("+libext+" in content or "--libext" in content or "-Y" in content)
        assert has_libdir, "compile.f missing library directory (-y/--libdir)"
        assert has_libext, "compile.f missing library extension (+libext+/--libext)"

    def test_compile_f_has_top_module(self):
        with open("/app/compile.f") as f:
            content = f.read()
        assert "--top" in content and "soc_top" in content, \
            "compile.f must specify --top soc_top"

    def test_compile_f_includes_gpio_bank(self):
        """Command file must include gpio_bank.sv source."""
        with open("/app/compile.f") as f:
            content = f.read()
        assert "gpio_bank" in content, \
            "compile.f must include gpio_bank.sv in the source list"

    def test_slang_compiles_successfully(self):
        slang = _find_slang()
        result = subprocess.run(
            [slang, "-f", "/app/compile.f"],
            capture_output=True, text=True, timeout=120,
            cwd="/app"
        )
        assert result.returncode == 0, (
            f"slang compilation failed (exit {result.returncode}).\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )


class TestAnalysisJson:
    """Verify analysis.json has correct hierarchy, ports, and parameter values."""

    @pytest.fixture(autouse=True)
    def load_analysis(self):
        assert os.path.isfile("/app/analysis.json"), "/app/analysis.json not found"
        with open("/app/analysis.json") as f:
            self.data = json.load(f)

    def test_top_module(self):
        assert self.data.get("top_module") == "soc_top"

    def test_total_instances(self):
        """Design has exactly 6 module instantiations."""
        assert self.data.get("total_instances") == 6

    def test_hierarchy_keys(self):
        hier = self.data.get("hierarchy", {})
        assert "soc_top" in hier, "hierarchy missing soc_top"
        assert "cpu_core" in hier, "hierarchy missing cpu_core"

    def test_soc_top_children(self):
        """soc_top instantiates cpu_core, gpio_bank, sync_fifo, uart_tx."""
        hier = self.data.get("hierarchy", {})
        children = sorted(hier.get("soc_top", []))
        assert children == ["cpu_core", "gpio_bank", "sync_fifo", "uart_tx"], \
            f"soc_top children: expected ['cpu_core', 'gpio_bank', 'sync_fifo', 'uart_tx'], got {children}"

    def test_cpu_core_children(self):
        """cpu_core instantiates alu and regfile."""
        hier = self.data.get("hierarchy", {})
        children = sorted(hier.get("cpu_core", []))
        assert children == ["alu", "regfile"], \
            f"cpu_core children: expected ['alu', 'regfile'], got {children}"

    def test_module_ports_structure(self):
        """module_ports must have entries for all 7 modules."""
        ports = self.data.get("module_ports", {})
        expected_modules = {"soc_top", "cpu_core", "alu", "regfile",
                            "sync_fifo", "uart_tx", "gpio_bank"}
        assert set(ports.keys()) == expected_modules, \
            f"module_ports keys: expected {expected_modules}, got {set(ports.keys())}"

    def test_alu_ports(self):
        """alu: 3 inputs (op, a, b), 3 outputs (result, zero, carry)."""
        ports = self.data["module_ports"]["alu"]
        assert ports["inputs"] == 3, f"alu inputs: expected 3, got {ports['inputs']}"
        assert ports["outputs"] == 3, f"alu outputs: expected 3, got {ports['outputs']}"

    def test_regfile_ports(self):
        """regfile: 7 inputs, 2 outputs."""
        ports = self.data["module_ports"]["regfile"]
        assert ports["inputs"] == 7, f"regfile inputs: expected 7, got {ports['inputs']}"
        assert ports["outputs"] == 2, f"regfile outputs: expected 2, got {ports['outputs']}"

    def test_cpu_core_ports(self):
        """cpu_core: 7 inputs, 2 outputs."""
        ports = self.data["module_ports"]["cpu_core"]
        assert ports["inputs"] == 7, f"cpu_core inputs: expected 7, got {ports['inputs']}"
        assert ports["outputs"] == 2, f"cpu_core outputs: expected 2, got {ports['outputs']}"

    def test_sync_fifo_ports(self):
        """sync_fifo: 5 inputs, 4 outputs."""
        ports = self.data["module_ports"]["sync_fifo"]
        assert ports["inputs"] == 5, f"sync_fifo inputs: expected 5, got {ports['inputs']}"
        assert ports["outputs"] == 4, f"sync_fifo outputs: expected 4, got {ports['outputs']}"

    def test_uart_tx_ports(self):
        """uart_tx: 4 inputs, 3 outputs."""
        ports = self.data["module_ports"]["uart_tx"]
        assert ports["inputs"] == 4, f"uart_tx inputs: expected 4, got {ports['inputs']}"
        assert ports["outputs"] == 3, f"uart_tx outputs: expected 3, got {ports['outputs']}"

    def test_soc_top_ports(self):
        """soc_top: 3 inputs (clk, rst_n, gpio_in), 3 outputs (gpio_out, uart_txd, gpio_irq)."""
        ports = self.data["module_ports"]["soc_top"]
        assert ports["inputs"] == 3, f"soc_top inputs: expected 3, got {ports['inputs']}"
        assert ports["outputs"] == 3, f"soc_top outputs: expected 3, got {ports['outputs']}"

    def test_gpio_bank_ports(self):
        """gpio_bank: 6 inputs, 3 outputs."""
        ports = self.data["module_ports"]["gpio_bank"]
        assert ports["inputs"] == 6, f"gpio_bank inputs: expected 6, got {ports['inputs']}"
        assert ports["outputs"] == 3, f"gpio_bank outputs: expected 3, got {ports['outputs']}"

    def test_instance_params_u_cpu(self):
        params = self.data.get("instance_params", {})
        assert "u_cpu" in params, "instance_params missing u_cpu"
        assert params["u_cpu"].get("WIDTH") == 32

    def test_instance_params_u_rf(self):
        params = self.data.get("instance_params", {})
        assert "u_rf" in params, "instance_params missing u_rf"
        assert params["u_rf"].get("NUM_REGS") == 16
        assert params["u_rf"].get("DATA_W") == 32

    def test_instance_params_u_fifo(self):
        params = self.data.get("instance_params", {})
        assert "u_fifo" in params, "instance_params missing u_fifo"
        assert params["u_fifo"].get("DEPTH") == 8
        assert params["u_fifo"].get("WIDTH") == 8

    def test_instance_params_u_uart(self):
        """u_uart CLKS_PER_BIT must be 434 (50000000/115200)."""
        params = self.data.get("instance_params", {})
        assert "u_uart" in params, "instance_params missing u_uart"
        assert params["u_uart"].get("CLKS_PER_BIT") == 434, \
            f"u_uart CLKS_PER_BIT: expected 434, got {params['u_uart'].get('CLKS_PER_BIT')}"

    def test_instance_params_u_gpio(self):
        """u_gpio must have NUM_PINS=8, DEBOUNCE_CYCLES=4."""
        params = self.data.get("instance_params", {})
        assert "u_gpio" in params, "instance_params missing u_gpio"
        assert params["u_gpio"].get("NUM_PINS") == 8, \
            f"u_gpio NUM_PINS: expected 8, got {params['u_gpio'].get('NUM_PINS')}"
        assert params["u_gpio"].get("DEBOUNCE_CYCLES") == 4, \
            f"u_gpio DEBOUNCE_CYCLES: expected 4, got {params['u_gpio'].get('DEBOUNCE_CYCLES')}"


class TestGenerateBlocks:
    """Verify generate block analysis in analysis.json."""

    @pytest.fixture(autouse=True)
    def load_analysis(self):
        assert os.path.isfile("/app/analysis.json"), "/app/analysis.json not found"
        with open("/app/analysis.json") as f:
            self.data = json.load(f)

    def test_generate_blocks_key_exists(self):
        assert "generate_blocks" in self.data, "analysis.json missing generate_blocks"

    def test_gpio_bank_has_generate(self):
        """gpio_bank must have a generate block entry."""
        gen = self.data.get("generate_blocks", {})
        assert "gpio_bank" in gen, "generate_blocks missing gpio_bank"

    def test_gpio_bank_gen_pin_name(self):
        """gpio_bank generate block must be named gen_pin."""
        gen = self.data["generate_blocks"]["gpio_bank"]
        assert isinstance(gen, list), "gpio_bank generate_blocks must be a list"
        assert len(gen) >= 1, "gpio_bank must have at least one generate block"
        names = [g.get("name", "") for g in gen]
        assert "gen_pin" in names, f"Expected gen_pin in generate blocks, got {names}"

    def test_gpio_bank_gen_pin_count(self):
        """gen_pin must have count=8 (NUM_PINS=8 after elaboration)."""
        gen = self.data["generate_blocks"]["gpio_bank"]
        gen_pin = next((g for g in gen if g.get("name") == "gen_pin"), None)
        assert gen_pin is not None, "gen_pin not found in generate_blocks"
        assert gen_pin.get("count") == 8, \
            f"gen_pin count: expected 8, got {gen_pin.get('count')}"


class TestFsmStates:
    """Verify FSM state encoding extraction in analysis.json."""

    @pytest.fixture(autouse=True)
    def load_analysis(self):
        assert os.path.isfile("/app/analysis.json"), "/app/analysis.json not found"
        with open("/app/analysis.json") as f:
            self.data = json.load(f)

    def test_fsm_states_key_exists(self):
        assert "fsm_states" in self.data, "analysis.json missing fsm_states"

    def test_uart_tx_has_fsm(self):
        """uart_tx must have FSM state entries."""
        fsm = self.data.get("fsm_states", {})
        assert "uart_tx" in fsm, "fsm_states missing uart_tx"

    def test_uart_tx_idle_state(self):
        states = self.data["fsm_states"]["uart_tx"]
        assert states.get("IDLE") == 0, f"IDLE: expected 0, got {states.get('IDLE')}"

    def test_uart_tx_start_state(self):
        states = self.data["fsm_states"]["uart_tx"]
        assert states.get("START") == 1, f"START: expected 1, got {states.get('START')}"

    def test_uart_tx_data_state(self):
        states = self.data["fsm_states"]["uart_tx"]
        assert states.get("DATA") == 2, f"DATA: expected 2, got {states.get('DATA')}"

    def test_uart_tx_stop_state(self):
        states = self.data["fsm_states"]["uart_tx"]
        assert states.get("STOP") == 3, f"STOP: expected 3, got {states.get('STOP')}"

    def test_uart_tx_done_state(self):
        states = self.data["fsm_states"]["uart_tx"]
        assert states.get("DONE") == 4, f"DONE: expected 4, got {states.get('DONE')}"

    def test_uart_tx_state_count(self):
        """uart_tx must have exactly 5 FSM states."""
        states = self.data["fsm_states"]["uart_tx"]
        assert len(states) == 5, f"uart_tx states: expected 5, got {len(states)}"


class TestMemoryArrays:
    """Verify memory array extraction in analysis.json."""

    @pytest.fixture(autouse=True)
    def load_analysis(self):
        assert os.path.isfile("/app/analysis.json"), "/app/analysis.json not found"
        with open("/app/analysis.json") as f:
            self.data = json.load(f)

    def test_memory_arrays_key_exists(self):
        assert "memory_arrays" in self.data, "analysis.json missing memory_arrays"

    def test_sync_fifo_has_arrays(self):
        arrays = self.data.get("memory_arrays", {})
        assert "sync_fifo" in arrays, "memory_arrays missing sync_fifo"

    def test_sync_fifo_mem_dimensions(self):
        """sync_fifo.mem: depth=8 (DEPTH param), width=8 (WIDTH param)."""
        arrays = self.data["memory_arrays"]["sync_fifo"]
        mem = next((a for a in arrays if a.get("name") == "mem"), None)
        assert mem is not None, "sync_fifo memory array 'mem' not found"
        assert mem.get("depth") == 8, \
            f"sync_fifo.mem depth: expected 8, got {mem.get('depth')}"
        assert mem.get("width") == 8, \
            f"sync_fifo.mem width: expected 8, got {mem.get('width')}"

    def test_regfile_has_arrays(self):
        arrays = self.data.get("memory_arrays", {})
        assert "regfile" in arrays, "memory_arrays missing regfile"

    def test_regfile_mem_dimensions(self):
        """regfile.mem: depth=16 (NUM_REGS param), width=32 (DATA_W param)."""
        arrays = self.data["memory_arrays"]["regfile"]
        mem = next((a for a in arrays if a.get("name") == "mem"), None)
        assert mem is not None, "regfile memory array 'mem' not found"
        assert mem.get("depth") == 16, \
            f"regfile.mem depth: expected 16, got {mem.get('depth')}"
        assert mem.get("width") == 32, \
            f"regfile.mem width: expected 32, got {mem.get('width')}"


class TestAnalyzeScript:
    """Verify analyze.py exists and is a real script."""

    def test_analyze_py_exists(self):
        assert os.path.isfile("/app/analyze.py"), "/app/analyze.py not found"

    def test_analyze_py_reads_ast(self):
        """analyze.py must reference AST JSON data, not just hardcode values."""
        with open("/app/analyze.py") as f:
            content = f.read()
        uses_json = "json" in content
        refs_ast = "ast" in content.lower() or "slang" in content.lower()
        assert uses_json and refs_ast, \
            "analyze.py must parse slang AST output, not hardcode values"

    def test_ast_json_exists(self):
        assert os.path.isfile("/app/ast.json"), "/app/ast.json not found"

    def test_ast_json_valid(self):
        with open("/app/ast.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "ast.json root must be a JSON object"
