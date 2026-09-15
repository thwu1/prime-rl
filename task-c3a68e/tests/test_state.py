
"""
Tests for the Hubris RTOS Configuration Audit and Repair.

Verifies:
  - All 7 configuration bugs are detected in the original config
  - ARM Cortex-M MPU-aligned memory layout is computed correctly
  - IPC dependency graph with cycle detection and priority inversion analysis
  - Corrected configuration resolves all issues (property-based)
  - Graphviz dependency graph is generated
  - Optimization report compares original vs fixed
"""

import json
import os
import tomllib
import pytest


def load_json(path):
    with open(path) as f:
        return json.load(f)


def flatten(obj):
    """JSON-serialize an object to a lowercase string for flexible substring matching."""
    return json.dumps(obj, default=str).lower()


def find_error(errors, *required, any_of=None):
    """Return True if any error contains ALL required substrings and at least one from any_of."""
    for e in errors:
        s = flatten(e)
        if all(r.lower() in s for r in required):
            if any_of is None or any(a.lower() in s for a in any_of):
                return True
    return False


def get_errors(data):
    """Normalize the validation errors to a list, handling various wrapper formats."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("errors", "validation_errors", "issues", "results"):
            if key in data and isinstance(data[key], list):
                return data[key]
        if all(isinstance(v, dict) for v in data.values()):
            return list(data.values())
    return []


def next_pow2(n):
    if n <= 1:
        return 1
    p = 1
    while p < n:
        p <<= 1
    return p


def align_up(addr, alignment):
    if alignment == 0:
        return addr
    return ((addr + alignment - 1) // alignment) * alignment


# ---------------------------------------------------------------------------
# Output file existence
# ---------------------------------------------------------------------------

class TestOutputFilesExist:
    def test_validation_errors_exists(self):
        assert os.path.isfile("/app/output/validation_errors.json"), \
            "Missing /app/output/validation_errors.json"

    def test_memory_layout_exists(self):
        assert os.path.isfile("/app/output/memory_layout.json"), \
            "Missing /app/output/memory_layout.json"

    def test_task_graph_exists(self):
        assert os.path.isfile("/app/output/task_graph.json"), \
            "Missing /app/output/task_graph.json"

    def test_fixed_app_toml_exists(self):
        assert os.path.isfile("/app/output/fixed_app.toml"), \
            "Missing /app/output/fixed_app.toml"

    def test_task_graph_dot_exists(self):
        assert os.path.isfile("/app/output/task_graph.dot"), \
            "Missing /app/output/task_graph.dot"

    def test_task_graph_svg_exists(self):
        assert os.path.isfile("/app/output/task_graph.svg"), \
            "Missing /app/output/task_graph.svg"

    def test_optimization_report_exists(self):
        assert os.path.isfile("/app/output/optimization_report.json"), \
            "Missing /app/output/optimization_report.json"


# ---------------------------------------------------------------------------
# Validation error detection — 7 distinct bugs
# ---------------------------------------------------------------------------

class TestValidationErrors:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.errors = get_errors(load_json("/app/output/validation_errors.json"))

    def test_peripheral_conflict_gpio_b(self):
        """Bug 1: spi_driver and i2c_driver both claim gpio_b."""
        assert find_error(
            self.errors, "gpio_b",
            any_of=["conflict", "exclusive", "shared", "duplicate", "multiple",
                     "already", "both", "claimed", "violation"]
        ), "Expected peripheral conflict error for gpio_b (spi_driver vs i2c_driver)"

    def test_nonexistent_peripheral_dma2(self):
        """Bug 2: crypto references peripheral dma2 not in chip.toml."""
        assert find_error(
            self.errors, "dma2",
            any_of=["nonexistent", "not found", "not defined", "undefined",
                     "unknown", "invalid", "does not exist", "missing"]
        ), "Expected nonexistent peripheral error for dma2"

    def test_interrupt_notification_mismatch(self):
        """Bug 3: net task maps eth_irq interrupt but eth_irq not in its notifications."""
        assert find_error(
            self.errors, "eth_irq",
            any_of=["notification", "mismatch", "missing", "undeclared",
                     "not declared", "not listed", "not in", "absent"]
        ), "Expected interrupt-notification mismatch error for eth_irq on net task"

    def test_ram_overflow(self):
        """Bug 4: total RAM with MPU alignment exceeds 512 KB."""
        assert find_error(
            self.errors,
            any_of=["overflow", "exceed", "insufficient", "capacity",
                     "not fit", "too large", "out of", "exhausted"]
        ), "Expected RAM overflow error"

    def test_priority_inversion(self):
        """Bug 5: sys_monitor (P1) depends on logger (P4) — priority inversion."""
        assert find_error(
            self.errors, "sys_monitor", "logger",
            any_of=["priority", "inversion"]
        ), "Expected priority inversion error for sys_monitor -> logger"

    def test_circular_dependency(self):
        """Bug 6: sys_monitor <-> logger cycle via task-slots."""
        assert find_error(
            self.errors, "sys_monitor", "logger",
            any_of=["cycle", "circular", "deadlock", "loop"]
        ), "Expected circular dependency error involving sys_monitor and logger"

    def test_nonexistent_task_hash_driver(self):
        """Bug 7: crypto references hash_driver in task-slots, which doesn't exist."""
        assert find_error(
            self.errors, "hash_driver",
            any_of=["nonexistent", "not found", "not defined", "undefined",
                     "unknown", "invalid", "does not exist", "missing", "no task"]
        ), "Expected nonexistent task-slot reference error for hash_driver"

    def test_minimum_error_count(self):
        """Should find at least 7 distinct errors."""
        assert len(self.errors) >= 7, \
            f"Expected at least 7 errors, found {len(self.errors)}"


# ---------------------------------------------------------------------------
# Memory layout — MPU-aligned addresses
# ---------------------------------------------------------------------------

class TestMemoryLayout:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.layout = load_json("/app/output/memory_layout.json")

    def _flash(self):
        return self.layout.get("flash", {})

    def _ram(self):
        return self.layout.get("ram", {})

    def _addr(self, region, name):
        entry = region.get(name, {})
        if isinstance(entry, dict):
            for k in ("address", "addr", "start", "base"):
                if k in entry:
                    v = entry[k]
                    return int(v, 0) if isinstance(v, str) else v
        return None

    def _size(self, region, name):
        entry = region.get(name, {})
        if isinstance(entry, dict):
            v = entry.get("size")
            if v is not None:
                return int(v, 0) if isinstance(v, str) else v
        return None

    # — Flash layout checks —

    def test_kernel_flash_address(self):
        assert self._addr(self._flash(), "kernel") == 0x08000000

    def test_kernel_flash_size(self):
        assert self._size(self._flash(), "kernel") == 32768

    def test_jefe_flash_address(self):
        assert self._addr(self._flash(), "jefe") == 0x08008000

    def test_sys_monitor_flash_aligned(self):
        """After rcc_driver ends at 0x0800E000, 16384-byte sys_monitor must align to 0x08010000."""
        assert self._addr(self._flash(), "sys_monitor") == 0x08010000

    def test_net_flash_aligned(self):
        """65536-byte net task must be 64KB-aligned => 0x08030000."""
        assert self._addr(self._flash(), "net") == 0x08030000

    def test_sensor_hub_flash_address(self):
        assert self._addr(self._flash(), "sensor_hub") == 0x08040000

    def test_update_server_flash_aligned(self):
        """After logger ends at 0x08054000, 32768-byte update_server aligns to 0x08058000."""
        assert self._addr(self._flash(), "update_server") == 0x08058000

    # — RAM layout checks —

    def test_kernel_ram_address(self):
        assert self._addr(self._ram(), "kernel") == 0x24000000

    def test_kernel_ram_size(self):
        assert self._size(self._ram(), "kernel") == 8192

    def test_jefe_ram_address(self):
        assert self._addr(self._ram(), "jefe") == 0x24002000

    def test_sys_monitor_ram_aligned(self):
        """After rcc_driver ends at 0x24003800, 4096-byte sys_monitor aligns to 0x24004000."""
        assert self._addr(self._ram(), "sys_monitor") == 0x24004000

    def test_net_driver_ram_aligned(self):
        """32768-byte net_driver after i2c_driver (end 0x24006000) aligns to 0x24008000."""
        assert self._addr(self._ram(), "net_driver") == 0x24008000

    def test_crypto_ram_address(self):
        """8192-byte crypto at 0x24012000 (after usart_driver end 0x24012000)."""
        assert self._addr(self._ram(), "crypto") == 0x24012000

    def test_sensor_hub_ram_aligned(self):
        """262144-byte sensor_hub must be 256KB-aligned => 0x24040000."""
        assert self._addr(self._ram(), "sensor_hub") == 0x24040000

    # — Overflow flags —

    def test_ram_overflow_detected(self):
        overflow = self.layout.get("ram_overflow")
        if overflow is None:
            overflow = self.layout.get("overflow", {}).get("ram")
        assert overflow is True, "RAM overflow should be detected"

    def test_flash_no_overflow(self):
        overflow = self.layout.get("flash_overflow")
        if overflow is None:
            overflow = self.layout.get("overflow", {}).get("flash")
        # False or absent both acceptable
        assert overflow in (False, None), "Flash should not overflow"


# ---------------------------------------------------------------------------
# Task dependency graph
# ---------------------------------------------------------------------------

class TestTaskGraph:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.graph = load_json("/app/output/task_graph.json")

    def _edge_set(self):
        edges = self.graph.get("edges", [])
        result = set()
        for e in edges:
            if isinstance(e, list) and len(e) == 2:
                result.add((e[0], e[1]))
            elif isinstance(e, dict):
                src = e.get("from", e.get("source", e.get("src")))
                tgt = e.get("to", e.get("target", e.get("dst")))
                if src and tgt:
                    result.add((src, tgt))
        return result

    def test_sys_monitor_to_logger_edge(self):
        assert ("sys_monitor", "logger") in self._edge_set()

    def test_logger_to_sys_monitor_edge(self):
        assert ("logger", "sys_monitor") in self._edge_set()

    def test_usart_driver_to_rcc_edge(self):
        assert ("usart_driver", "rcc_driver") in self._edge_set()

    def test_net_to_net_driver_edge(self):
        assert ("net", "net_driver") in self._edge_set()

    def test_sensor_hub_edges(self):
        es = self._edge_set()
        assert ("sensor_hub", "i2c_driver") in es
        assert ("sensor_hub", "spi_driver") in es

    def test_rcc_driver_has_multiple_dependents(self):
        es = self._edge_set()
        rcc_deps = {src for src, tgt in es if tgt == "rcc_driver"}
        assert len(rcc_deps) >= 3, \
            f"Expected >=3 tasks depending on rcc_driver, got {rcc_deps}"

    def test_cycle_detected(self):
        cycles = self.graph.get("cycles", [])
        assert len(cycles) >= 1, "Should detect at least one cycle"
        found = False
        for cycle in cycles:
            members = set(cycle)
            if "sys_monitor" in members and "logger" in members:
                found = True
                break
        assert found, "Should detect cycle involving sys_monitor and logger"

    def test_priority_inversion_detected(self):
        inversions = self.graph.get("priority_inversions", [])
        assert len(inversions) >= 1, "Should detect at least one priority inversion"
        found = False
        for inv in inversions:
            inv_str = flatten(inv)
            if "sys_monitor" in inv_str and "logger" in inv_str:
                found = True
                break
        assert found, "Should detect priority inversion between sys_monitor and logger"

    def test_total_edge_count(self):
        """There should be 12 edges between existing tasks."""
        es = self._edge_set()
        assert len(es) >= 10, \
            f"Expected at least 10 IPC edges, found {len(es)}"


# ---------------------------------------------------------------------------
# Fixed configuration — property-based validation
# ---------------------------------------------------------------------------

class TestFixedConfig:
    """Verify the corrected configuration resolves all issues."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with open("/app/output/fixed_app.toml", "rb") as f:
            self.fixed = tomllib.load(f)
        with open("/app/config/chip.toml", "rb") as f:
            self.chip = tomllib.load(f)
        self.tasks = self.fixed.get("tasks", {})
        self.chip_periphs = set(self.chip.get("peripherals", {}).keys())

    def test_all_original_tasks_present(self):
        """Must not delete tasks to fix issues."""
        expected = {"jefe", "rcc_driver", "sys_monitor", "usart_driver",
                    "spi_driver", "i2c_driver", "net_driver", "net",
                    "sensor_hub", "crypto", "storage", "update_server",
                    "logger", "idle"}
        actual = set(self.tasks.keys())
        missing = expected - actual
        assert not missing, f"Missing tasks in fixed config: {missing}"

    def test_no_peripheral_conflicts(self):
        """No peripheral claimed by multiple tasks."""
        from collections import Counter
        all_uses = []
        for tname, tcfg in self.tasks.items():
            for p in tcfg.get("uses", []):
                all_uses.append(p)
        counts = Counter(all_uses)
        conflicts = {p: c for p, c in counts.items() if c > 1}
        assert not conflicts, f"Peripheral conflicts remain: {conflicts}"

    def test_all_peripherals_defined(self):
        """All referenced peripherals exist in chip.toml."""
        for tname, tcfg in self.tasks.items():
            for p in tcfg.get("uses", []):
                assert p in self.chip_periphs, \
                    f"Task '{tname}' uses undefined peripheral '{p}'"

    def test_all_task_slots_valid(self):
        """All task-slot references point to existing tasks."""
        for tname, tcfg in self.tasks.items():
            for slot in tcfg.get("task-slots", []):
                assert slot in self.tasks, \
                    f"Task '{tname}' references nonexistent task '{slot}'"

    def test_interrupt_notification_consistency(self):
        """All interrupt mappings have corresponding notifications."""
        for tname, tcfg in self.tasks.items():
            notifs = set(tcfg.get("notifications", []))
            for irq, notif_name in tcfg.get("interrupts", {}).items():
                assert notif_name in notifs, \
                    f"Task '{tname}': interrupt '{irq}' maps to " \
                    f"undeclared notification '{notif_name}'"

    def test_no_dependency_cycles(self):
        """No circular task-slot dependencies."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in self.tasks}

        adj = {}
        for tname, tcfg in self.tasks.items():
            adj[tname] = [s for s in tcfg.get("task-slots", [])
                          if s in self.tasks]

        def has_cycle(u):
            color[u] = GRAY
            for v in adj.get(u, []):
                if color[v] == GRAY:
                    return True
                if color[v] == WHITE and has_cycle(v):
                    return True
            color[u] = BLACK
            return False

        for node in sorted(self.tasks):
            if color[node] == WHITE:
                assert not has_cycle(node), \
                    "Circular dependency detected in fixed config"

    def test_no_priority_inversions(self):
        """No task depends on a lower-priority (higher number) task."""
        for tname, tcfg in self.tasks.items():
            my_prio = tcfg.get("priority", 255)
            for slot in tcfg.get("task-slots", []):
                if slot in self.tasks:
                    slot_prio = self.tasks[slot].get("priority", 255)
                    assert slot_prio <= my_prio, \
                        f"Priority inversion: '{tname}' (P{my_prio}) " \
                        f"depends on '{slot}' (P{slot_prio})"

    def test_ram_fits_within_capacity(self):
        """MPU-aligned RAM allocation must fit within 512KB."""
        kernel = self.fixed.get("kernel", {})
        kreq = kernel.get("requires", {})
        kram = kreq.get("ram", 0)

        ram_base = self.chip["memory"]["ram"]["address"]
        ram_total = self.chip["memory"]["ram"]["size"]

        kr_sz = next_pow2(kram)
        ram_pos = align_up(ram_base, kr_sz)
        ram_pos += kr_sz

        sorted_tasks = sorted(
            self.tasks.items(),
            key=lambda x: (x[1].get("priority", 255), x[0])
        )
        for tname, tcfg in sorted_tasks:
            tr = tcfg.get("max-sizes", {}).get("ram", 0)
            if tr > 0:
                tr_sz = next_pow2(tr)
                ram_pos = align_up(ram_pos, tr_sz)
                ram_pos += tr_sz

        assert ram_pos <= ram_base + ram_total, \
            f"Fixed config RAM overflow: needs {ram_pos - ram_base} " \
            f"bytes, have {ram_total}"

    def test_flash_fits_within_capacity(self):
        """MPU-aligned flash allocation must fit within capacity."""
        kernel = self.fixed.get("kernel", {})
        kreq = kernel.get("requires", {})
        kflash = kreq.get("flash", 0)

        flash_base = self.chip["memory"]["flash"]["address"]
        flash_total = self.chip["memory"]["flash"]["size"]

        kf_sz = next_pow2(kflash)
        flash_pos = align_up(flash_base, kf_sz)
        flash_pos += kf_sz

        sorted_tasks = sorted(
            self.tasks.items(),
            key=lambda x: (x[1].get("priority", 255), x[0])
        )
        for tname, tcfg in sorted_tasks:
            tf = tcfg.get("max-sizes", {}).get("flash", 0)
            if tf > 0:
                tf_sz = next_pow2(tf)
                flash_pos = align_up(flash_pos, tf_sz)
                flash_pos += tf_sz

        assert flash_pos <= flash_base + flash_total, \
            "Fixed config flash overflow"

    def test_sensor_hub_ram_reduced(self):
        """sensor_hub RAM must be reduced from the original 262144."""
        sh_ram = self.tasks.get("sensor_hub", {}).get(
            "max-sizes", {}).get("ram", 0)
        assert sh_ram < 262144, \
            f"sensor_hub RAM not reduced: {sh_ram}"
        assert sh_ram >= 32768, \
            f"sensor_hub RAM too small for actual usage: {sh_ram}"

    def test_crypto_no_invalid_dma(self):
        """crypto task must not reference unavailable dma2."""
        uses = self.tasks.get("crypto", {}).get("uses", [])
        assert "dma2" not in uses, \
            "crypto still references unavailable dma2"


# ---------------------------------------------------------------------------
# Graph visualization
# ---------------------------------------------------------------------------

class TestGraphVisualization:
    def test_dot_contains_digraph(self):
        with open("/app/output/task_graph.dot") as f:
            content = f.read()
        assert "digraph" in content.lower(), \
            "DOT file must contain a digraph definition"

    def test_dot_contains_task_nodes(self):
        with open("/app/output/task_graph.dot") as f:
            content = f.read()
        for task in ["jefe", "net", "sensor_hub", "crypto", "logger",
                     "sys_monitor", "rcc_driver"]:
            assert task in content, f"DOT file missing node for {task}"

    def test_svg_is_valid(self):
        with open("/app/output/task_graph.svg") as f:
            content = f.read()
        assert "<svg" in content.lower(), \
            "SVG file doesn't contain valid SVG markup"
        assert len(content) > 500, \
            "SVG file too small — likely not a rendered graph"

    def test_dot_contains_edges(self):
        with open("/app/output/task_graph.dot") as f:
            content = f.read()
        assert "->" in content, \
            "DOT file must contain directed edges (->)"


# ---------------------------------------------------------------------------
# Optimization report
# ---------------------------------------------------------------------------

class TestOptimizationReport:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_json("/app/output/optimization_report.json")

    def test_has_ram_capacity(self):
        """Report must include RAM capacity."""
        assert "ram_capacity" in self.report, \
            "Report missing ram_capacity field"
        assert self.report["ram_capacity"] == 524288, \
            "RAM capacity should be 524288 (512 KB)"

    def test_original_overflow_true(self):
        """Original config must show RAM overflow."""
        assert self.report.get("original_overflow") is True, \
            "original_overflow should be True"

    def test_fixed_overflow_false(self):
        """Fixed config must not overflow."""
        assert self.report.get("fixed_overflow") is False, \
            "fixed_overflow should be False"

    def test_fixed_ram_less_than_capacity(self):
        """Fixed RAM usage must be less than capacity."""
        fixed = self.report.get("fixed_ram_used", float("inf"))
        cap = self.report.get("ram_capacity", 524288)
        assert fixed < cap, \
            f"Fixed RAM used ({fixed}) exceeds capacity ({cap})"

    def test_original_ram_exceeds_capacity(self):
        """Original RAM usage must exceed capacity (overflow)."""
        orig = self.report.get("original_ram_used", 0)
        cap = self.report.get("ram_capacity", 524288)
        assert orig > cap, \
            f"Original RAM used ({orig}) should exceed capacity ({cap})"

    def test_fixes_documented(self):
        """Report must document applied fixes."""
        fixes = self.report.get("fixes_applied", [])
        assert isinstance(fixes, list), "fixes_applied must be a list"
        assert len(fixes) >= 5, \
            f"Expected at least 5 documented fixes, found {len(fixes)}"

    def test_fixes_have_justifications(self):
        """Each fix must include a justification."""
        fixes = self.report.get("fixes_applied", [])
        for i, fix in enumerate(fixes):
            assert "justification" in fix, \
                f"Fix {i} missing justification field"
            assert len(fix["justification"]) > 10, \
                f"Fix {i} justification too short"
