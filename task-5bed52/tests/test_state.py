#!/usr/bin/env python3

"""Tests for the TAC dataflow analysis, optimization, and pipeline artifacts."""

import json
import os
import subprocess
import re
import pytest

RESULTS_DIR = "/app/results"
PROGRAMS_DIR = "/app/programs"


def setup_module(module):
    """Run the optimization pipeline if results don't exist yet."""
    if not os.path.exists(os.path.join(RESULTS_DIR, "prog1.cfg.json")):
        if os.path.exists("/app/Makefile"):
            result = subprocess.run(
                ["make", "all"],
                capture_output=True, text=True, timeout=180,
                cwd="/app"
            )
            if result.returncode != 0 and os.path.exists("/app/optimizer.py"):
                # Makefile failed, try optimizer directly for partial credit
                subprocess.run(
                    ["python3", "/app/optimizer.py"],
                    capture_output=True, text=True, timeout=120,
                    cwd="/app"
                )
        elif os.path.exists("/app/optimizer.py"):
            result = subprocess.run(
                ["python3", "/app/optimizer.py"],
                capture_output=True, text=True, timeout=120,
                cwd="/app"
            )
            assert result.returncode == 0, (
                f"optimizer.py failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )
        else:
            pytest.skip("Neither Makefile nor optimizer.py found at /app/")


def load_json(basename, suffix):
    path = os.path.join(RESULTS_DIR, f"{basename}.{suffix}")
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)


def load_tac(basename, suffix="opt.tac"):
    path = os.path.join(RESULTS_DIR, f"{basename}.{suffix}")
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        return f.read()


def count_instructions(tac_text):
    """Count non-label, non-FUNC/ENDFUNC lines."""
    count = 0
    for line in tac_text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith("FUNC ") or line == "ENDFUNC":
            continue
        if re.match(r'^\w+\s*:$', line):
            continue
        count += 1
    return count


# ============================================================
# Simple TAC interpreter for semantic equivalence checking
# ============================================================

def interpret_tac(tac_text):
    """Interpret a TAC function and return the RETURN value."""
    lines = tac_text.strip().split('\n')
    blocks = {}
    block_order = []
    current_label = None
    current_instrs = []
    in_func = False

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("FUNC "):
            in_func = True
            continue
        if line == "ENDFUNC":
            if current_label is not None:
                blocks[current_label] = current_instrs
            break
        m = re.match(r'^(\w+)\s*:$', line)
        if m:
            if current_label is not None:
                blocks[current_label] = current_instrs
            current_label = m.group(1)
            block_order.append(current_label)
            current_instrs = []
            continue
        current_instrs.append(line)

    if not block_order:
        return None

    env = {}
    current_block = block_order[0]
    max_steps = 100000

    def resolve(val):
        try:
            return int(val)
        except ValueError:
            return env.get(val, 0)

    ops = {
        '+': lambda a, b: a + b,
        '-': lambda a, b: a - b,
        '*': lambda a, b: a * b,
        '/': lambda a, b: a // b if b != 0 else 0,
        '%': lambda a, b: a % b if b != 0 else 0,
        '==': lambda a, b: int(a == b),
        '!=': lambda a, b: int(a != b),
        '<': lambda a, b: int(a < b),
        '>': lambda a, b: int(a > b),
        '<=': lambda a, b: int(a <= b),
        '>=': lambda a, b: int(a >= b),
        '&&': lambda a, b: int(bool(a) and bool(b)),
        '||': lambda a, b: int(bool(a) or bool(b)),
    }

    step = 0
    while step < max_steps:
        instrs = blocks.get(current_block, [])
        block_idx = block_order.index(current_block) if current_block in block_order else -1
        jumped = False

        for instr in instrs:
            step += 1
            if step >= max_steps:
                return None

            # RETURN x
            m = re.match(r'^RETURN\s+(.+)$', instr)
            if m:
                return resolve(m.group(1).strip())

            # IF x GOTO label
            m = re.match(r'^IF\s+(\S+)\s+GOTO\s+(\w+)$', instr)
            if m:
                if resolve(m.group(1)):
                    current_block = m.group(2)
                    jumped = True
                    break
                continue

            # GOTO label
            m = re.match(r'^GOTO\s+(\w+)$', instr)
            if m:
                current_block = m.group(1)
                jumped = True
                break

            # NOP
            if instr == 'NOP':
                continue

            # PARAM (skip for now)
            if instr.startswith('PARAM '):
                continue

            # x = y op z (binary) - need multi-char ops
            m = re.match(r'^(\w+)\s*=\s*(\S+)\s+([\+\-\*/%]|==|!=|<=|>=|<|>|&&|\|\|)\s+(\S+)$', instr)
            if m:
                dst, s1, op, s2 = m.group(1), m.group(2), m.group(3), m.group(4)
                env[dst] = ops[op](resolve(s1), resolve(s2))
                continue

            # x = op y (unary)
            m = re.match(r'^(\w+)\s*=\s*([!\-])\s+(\S+)$', instr)
            if m:
                dst, op, s = m.group(1), m.group(2), m.group(3)
                if op == '-':
                    env[dst] = -resolve(s)
                elif op == '!':
                    env[dst] = int(not bool(resolve(s)))
                continue

            # x = val (copy or const)
            m = re.match(r'^(\w+)\s*=\s*(\S+)$', instr)
            if m:
                env[m.group(1)] = resolve(m.group(2))
                continue

        if not jumped:
            # fallthrough to next block
            if block_idx >= 0 and block_idx + 1 < len(block_order):
                current_block = block_order[block_idx + 1]
            else:
                return None

    return None


# ============================================================
# Test: All required output files exist
# ============================================================

class TestOutputFilesExist:
    @pytest.mark.parametrize("prog", ["prog1", "prog2", "prog3"])
    @pytest.mark.parametrize("suffix", [
        "cfg.json", "live.json", "reaching.json",
        "avail.json", "constprop.json", "opt.tac"
    ])
    def test_output_exists(self, prog, suffix):
        path = os.path.join(RESULTS_DIR, f"{prog}.{suffix}")
        assert os.path.exists(path), f"Missing: {path}"


# ============================================================
# Test: CFG structure
# ============================================================

class TestCFG:
    def test_prog1_cfg_entry(self):
        cfg = load_json("prog1", "cfg.json")
        assert set(cfg["entry"]) == {"loop", "end"}

    def test_prog1_cfg_loop(self):
        cfg = load_json("prog1", "cfg.json")
        assert set(cfg["loop"]) == {"loop", "end"}

    def test_prog1_cfg_end(self):
        cfg = load_json("prog1", "cfg.json")
        assert cfg["end"] == [] or set(cfg["end"]) == set()

    def test_prog2_cfg_entry(self):
        cfg = load_json("prog2", "cfg.json")
        assert set(cfg["entry"]) == {"then_b", "else_b"}

    def test_prog2_cfg_branches_to_merge(self):
        cfg = load_json("prog2", "cfg.json")
        assert set(cfg["then_b"]) == {"merge"}
        assert set(cfg["else_b"]) == {"merge"}

    def test_prog2_cfg_merge(self):
        cfg = load_json("prog2", "cfg.json")
        assert cfg["merge"] == [] or set(cfg["merge"]) == set()

    def test_prog3_cfg_structure(self):
        cfg = load_json("prog3", "cfg.json")
        assert set(cfg["entry"]) == {"outer_check"}
        assert set(cfg["outer_check"]) == {"outer_body", "done"}
        assert set(cfg["outer_body"]) == {"inner_check"}
        assert set(cfg["inner_check"]) == {"inner_body", "outer_next"}
        assert set(cfg["inner_body"]) == {"inner_check"}
        assert set(cfg["outer_next"]) == {"outer_check"}
        assert cfg["done"] == [] or set(cfg["done"]) == set()

    def test_prog3_all_blocks_present(self):
        cfg = load_json("prog3", "cfg.json")
        expected = {
            "entry", "outer_check", "outer_body",
            "inner_check", "inner_body", "outer_next", "done"
        }
        assert set(cfg.keys()) == expected


# ============================================================
# Test: Liveness analysis
# ============================================================

class TestLiveness:
    def test_prog1_entry_live_in(self):
        live = load_json("prog1", "live.json")
        assert live["entry"] == []

    def test_prog1_loop_live_in(self):
        live = load_json("prog1", "live.json")
        live_set = set(live["loop"])
        assert "a" in live_set
        assert "b" in live_set

    def test_prog1_end_live_in(self):
        live = load_json("prog1", "live.json")
        live_set = set(live["end"])
        assert "c" in live_set

    def test_prog2_entry_live_in(self):
        live = load_json("prog2", "live.json")
        assert live["entry"] == []

    def test_prog2_merge_live_in(self):
        live = load_json("prog2", "live.json")
        live_set = set(live["merge"])
        assert "c" in live_set
        assert "x" in live_set
        assert "y" in live_set

    def test_prog3_inner_body_live_in(self):
        live = load_json("prog3", "live.json")
        live_set = set(live["inner_body"])
        assert "i" in live_set
        assert "j" in live_set
        assert "sum" in live_set

    def test_prog3_dead_vars_not_live_at_done(self):
        live = load_json("prog3", "live.json")
        live_set = set(live["done"])
        assert "dead1" not in live_set
        assert "dead2" not in live_set
        assert "sum" in live_set

    def test_prog3_entry_live_in(self):
        live = load_json("prog3", "live.json")
        assert live["entry"] == []


# ============================================================
# Test: Reaching definitions
# ============================================================

class TestReachingDefinitions:
    def test_prog1_entry_empty(self):
        reach = load_json("prog1", "reaching.json")
        assert reach["entry"] == []

    def test_prog2_entry_empty(self):
        reach = load_json("prog2", "reaching.json")
        assert reach["entry"] == []

    def test_prog2_then_b_reaches(self):
        reach = load_json("prog2", "reaching.json")
        defs = reach["then_b"]
        assert ["x", "entry", 0] in defs
        assert ["y", "entry", 1] in defs
        assert ["z", "entry", 2] in defs

    def test_prog2_merge_has_both_branches(self):
        reach = load_json("prog2", "reaching.json")
        defs = reach["merge"]
        a_sources = [d[1] for d in defs if d[0] == "a"]
        assert "then_b" in a_sources
        assert "else_b" in a_sources

    def test_prog3_loop_back_edge(self):
        reach = load_json("prog3", "reaching.json")
        defs = reach["inner_check"]
        j_sources = [d[1] for d in defs if d[0] == "j"]
        assert "outer_body" in j_sources
        assert "inner_body" in j_sources


# ============================================================
# Test: Available expressions
# ============================================================

class TestAvailableExpressions:
    def test_prog1_entry_empty(self):
        avail = load_json("prog1", "avail.json")
        assert avail["entry"] == []

    def test_prog1_loop_has_a_plus_b(self):
        avail = load_json("prog1", "avail.json")
        exprs = [tuple(e) for e in avail["loop"]]
        assert ("a", "+", "b") in exprs

    def test_prog2_entry_empty(self):
        avail = load_json("prog2", "avail.json")
        assert avail["entry"] == []

    def test_prog2_then_b_has_x_times_y(self):
        avail = load_json("prog2", "avail.json")
        exprs = [tuple(e) for e in avail["then_b"]]
        assert ("x", "*", "y") in exprs

    def test_prog2_merge_has_x_times_y(self):
        avail = load_json("prog2", "avail.json")
        exprs = [tuple(e) for e in avail["merge"]]
        assert ("x", "*", "y") in exprs

    def test_prog3_inner_body_has_i_times_i(self):
        avail = load_json("prog3", "avail.json")
        exprs = [tuple(e) for e in avail["inner_body"]]
        assert ("i", "*", "i") in exprs

    def test_prog3_outer_body_empty(self):
        """After outer loop modifies i, i*i is killed at outer_check."""
        avail = load_json("prog3", "avail.json")
        assert avail["outer_body"] == []

    def test_prog3_entry_empty(self):
        avail = load_json("prog3", "avail.json")
        assert avail["entry"] == []


# ============================================================
# Test: Constant propagation
# ============================================================

class TestConstantPropagation:
    def test_prog1_entry_all_top(self):
        cp = load_json("prog1", "constprop.json")
        for var in cp["entry"]:
            assert cp["entry"][var] == "TOP"

    def test_prog1_loop_b_is_20(self):
        cp = load_json("prog1", "constprop.json")
        assert cp["loop"]["b"] == 20

    def test_prog1_loop_a_is_bot(self):
        """a is redefined in the loop, so it's BOT at loop entry."""
        cp = load_json("prog1", "constprop.json")
        assert cp["loop"]["a"] == "BOT"

    def test_prog2_entry_all_top(self):
        cp = load_json("prog2", "constprop.json")
        for var in cp["entry"]:
            assert cp["entry"][var] == "TOP"

    def test_prog2_then_b_constants(self):
        cp = load_json("prog2", "constprop.json")
        assert cp["then_b"]["x"] == 5
        assert cp["then_b"]["y"] == 3
        assert cp["then_b"]["z"] == 15

    def test_prog2_merge_a_is_bot(self):
        """a has different values from then_b (z+1=16) and else_b (z-1=14)."""
        cp = load_json("prog2", "constprop.json")
        assert cp["merge"]["a"] == "BOT"

    def test_prog2_merge_x_y_z_constant(self):
        cp = load_json("prog2", "constprop.json")
        assert cp["merge"]["x"] == 5
        assert cp["merge"]["y"] == 3
        assert cp["merge"]["z"] == 15

    def test_prog3_all_bot_in_loop(self):
        """Variables in nested loops are all BOT due to loop-carried deps."""
        cp = load_json("prog3", "constprop.json")
        for var in ["i", "j", "sum"]:
            assert cp["outer_check"][var] == "BOT"
            assert cp["inner_check"][var] == "BOT"


# ============================================================
# Test: Optimization quality
# ============================================================

class TestOptimization:
    def _orig_text(self, prog):
        with open(os.path.join(PROGRAMS_DIR, f"{prog}.tac")) as f:
            return f.read()

    def test_prog1_fewer_instructions(self):
        orig = count_instructions(self._orig_text("prog1"))
        opt = count_instructions(load_tac("prog1"))
        assert opt < orig, f"Expected fewer instructions: orig={orig}, opt={opt}"

    def test_prog2_fewer_instructions(self):
        orig = count_instructions(self._orig_text("prog2"))
        opt = count_instructions(load_tac("prog2"))
        assert opt < orig, f"Expected fewer instructions: orig={orig}, opt={opt}"

    def test_prog3_fewer_instructions(self):
        orig = count_instructions(self._orig_text("prog3"))
        opt = count_instructions(load_tac("prog3"))
        assert opt < orig, f"Expected fewer instructions: orig={orig}, opt={opt}"

    def test_prog1_semantic_equivalence(self):
        orig_val = interpret_tac(self._orig_text("prog1"))
        opt_val = interpret_tac(load_tac("prog1"))
        assert orig_val == opt_val, f"Semantic mismatch: orig={orig_val}, opt={opt_val}"

    def test_prog2_semantic_equivalence(self):
        orig_val = interpret_tac(self._orig_text("prog2"))
        opt_val = interpret_tac(load_tac("prog2"))
        assert orig_val == opt_val, f"Semantic mismatch: orig={orig_val}, opt={opt_val}"

    def test_prog3_semantic_equivalence(self):
        orig_val = interpret_tac(self._orig_text("prog3"))
        opt_val = interpret_tac(load_tac("prog3"))
        assert orig_val == opt_val, f"Semantic mismatch: orig={orig_val}, opt={opt_val}"

    def test_prog3_dead_code_removed(self):
        """dead1 and dead2 should be eliminated from the optimized code."""
        opt_text = load_tac("prog3")
        assert "dead1" not in opt_text
        assert "dead2" not in opt_text

    def test_prog3_t1_removed(self):
        """t1 = i*i in outer_body is dead code; should be eliminated."""
        opt_text = load_tac("prog3")
        assert "t1 =" not in opt_text and "t1=" not in opt_text

    def test_prog2_constants_folded(self):
        """z should be folded to 15 in the optimized output."""
        opt_text = load_tac("prog2")
        assert "z = 15" in opt_text or "z=15" in opt_text

    def test_prog1_b_eliminated(self):
        """b=20 is a constant propagated everywhere; b should not be assigned."""
        opt_text = load_tac("prog1")
        assert "b = 20" not in opt_text and "b=20" not in opt_text


# ============================================================
# Test: Output format validation
# ============================================================

class TestOutputFormat:
    @pytest.mark.parametrize("prog", ["prog1", "prog2", "prog3"])
    def test_cfg_is_dict_of_lists(self, prog):
        cfg = load_json(prog, "cfg.json")
        assert isinstance(cfg, dict)
        for k, v in cfg.items():
            assert isinstance(k, str)
            assert isinstance(v, list)

    @pytest.mark.parametrize("prog", ["prog1", "prog2", "prog3"])
    def test_live_is_dict_of_sorted_lists(self, prog):
        live = load_json(prog, "live.json")
        assert isinstance(live, dict)
        for k, v in live.items():
            assert isinstance(v, list)
            assert v == sorted(v), f"Live vars for {k} not sorted: {v}"

    @pytest.mark.parametrize("prog", ["prog1", "prog2", "prog3"])
    def test_reaching_is_dict_of_lists_of_triples(self, prog):
        reach = load_json(prog, "reaching.json")
        assert isinstance(reach, dict)
        for k, v in reach.items():
            assert isinstance(v, list)
            for item in v:
                assert len(item) == 3, (
                    f"Reaching def item should be [var, block, idx]: {item}"
                )

    @pytest.mark.parametrize("prog", ["prog1", "prog2", "prog3"])
    def test_avail_is_dict_of_lists_of_triples(self, prog):
        avail = load_json(prog, "avail.json")
        assert isinstance(avail, dict)
        for k, v in avail.items():
            assert isinstance(v, list)
            for item in v:
                assert len(item) == 3, (
                    f"Available expr should be [src1, op, src2]: {item}"
                )

    @pytest.mark.parametrize("prog", ["prog1", "prog2", "prog3"])
    def test_constprop_is_dict_of_dicts(self, prog):
        cp = load_json(prog, "constprop.json")
        assert isinstance(cp, dict)
        for k, v in cp.items():
            assert isinstance(v, dict)
            for var, val in v.items():
                assert isinstance(val, (int, str)), (
                    f"Const prop value should be int or string: {val}"
                )
                if isinstance(val, str):
                    assert val in ("TOP", "BOT"), (
                        f"String const prop value must be TOP or BOT: {val}"
                    )

    @pytest.mark.parametrize("prog", ["prog1", "prog2", "prog3"])
    def test_opt_tac_is_valid_tac(self, prog):
        opt = load_tac(prog)
        assert "FUNC " in opt
        assert "ENDFUNC" in opt
        assert "RETURN" in opt


# ============================================================
# Test: Makefile structure
# ============================================================

class TestMakefileStructure:
    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    @pytest.mark.parametrize("target", ["all", "analyze", "visualize", "report"])
    def test_makefile_has_target(self, target):
        assert os.path.exists("/app/Makefile"), "Makefile not found"
        with open("/app/Makefile") as f:
            content = f.read()
        assert re.search(rf'^{target}\s*:', content, re.MULTILINE), \
            f"Makefile missing target: {target}"


# ============================================================
# Test: CFG visualization (graphviz SVG output)
# ============================================================

class TestVisualization:
    @pytest.mark.parametrize("prog", ["prog1", "prog2", "prog3"])
    def test_svg_exists(self, prog):
        path = os.path.join(RESULTS_DIR, f"{prog}.cfg.svg")
        assert os.path.exists(path), f"Missing SVG: {path}"

    @pytest.mark.parametrize("prog", ["prog1", "prog2", "prog3"])
    def test_svg_is_valid_svg(self, prog):
        path = os.path.join(RESULTS_DIR, f"{prog}.cfg.svg")
        with open(path) as f:
            content = f.read()
        assert "<svg" in content.lower(), "SVG file does not contain <svg> element"

    def test_prog1_svg_contains_blocks(self):
        path = os.path.join(RESULTS_DIR, "prog1.cfg.svg")
        with open(path) as f:
            content = f.read()
        for block in ["entry", "loop", "end"]:
            assert block in content, f"SVG missing block node: {block}"

    def test_prog3_svg_contains_all_blocks(self):
        path = os.path.join(RESULTS_DIR, "prog3.cfg.svg")
        with open(path) as f:
            content = f.read()
        for block in ["entry", "outer_check", "outer_body",
                       "inner_check", "inner_body", "outer_next", "done"]:
            assert block in content, f"SVG missing block node: {block}"


# ============================================================
# Test: Summary report (jq-generated JSON)
# ============================================================

class TestSummaryReport:
    def test_summary_exists(self):
        path = os.path.join(RESULTS_DIR, "summary.json")
        assert os.path.exists(path), "summary.json not found in results"

    def test_summary_is_valid_json(self):
        path = os.path.join(RESULTS_DIR, "summary.json")
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_summary_has_all_programs(self):
        path = os.path.join(RESULTS_DIR, "summary.json")
        with open(path) as f:
            summary = json.load(f)
        for prog in ["prog1", "prog2", "prog3"]:
            assert prog in summary, f"summary.json missing key: {prog}"

    def test_summary_matches_constprop(self):
        path = os.path.join(RESULTS_DIR, "summary.json")
        with open(path) as f:
            summary = json.load(f)
        for prog in ["prog1", "prog2", "prog3"]:
            cp = load_json(prog, "constprop.json")
            assert summary[prog] == cp, \
                f"summary.json[{prog}] doesn't match {prog}.constprop.json"
