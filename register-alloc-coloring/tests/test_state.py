"""
Comprehensive tests for register allocation pipeline and x86-64 code generation:
  liveness analysis, interference graph, graph coloring, assembly emission.
"""
import sys
import os
import subprocess
import tempfile
sys.path.insert(0, '/app')

import pytest
from cfg import (
    CFG, BasicBlock, Instr, Callq, Jump, JumpIf,
    Var, Reg, Immediate, Deref,
    Location, reads_of, writes_of,
    CALLER_SAVE_REGS, ALLOCATABLE_REGS, REG_TO_COLOR, RESERVED_REGS,
)
from liveness import analyze_liveness
from interference import build_interference
from coloring import dsatur_color
from allocator import allocate_registers
from codegen import emit_x86


# ──────────────────────────────────────────────────────────────────────
# Helper: build a single-block CFG for simple tests
# ──────────────────────────────────────────────────────────────────────

def single_block_cfg(instrs):
    blocks = {'start': BasicBlock('start', instrs)}
    return CFG(entry='start', blocks=blocks)


# ──────────────────────────────────────────────────────────────────────
# 1. LIVENESS ANALYSIS TESTS
# ──────────────────────────────────────────────────────────────────────

class TestLiveness:

    def test_straight_line_live_after(self):
        """Verify live-after sets for straight-line code."""
        instrs = [
            Instr('movq', [Immediate(1), Var('v')]),        # 0
            Instr('movq', [Immediate(42), Var('w')]),       # 1
            Instr('movq', [Var('v'), Var('x')]),            # 2
            Instr('addq', [Immediate(7), Var('x')]),        # 3
            Instr('movq', [Var('x'), Var('y')]),            # 4
            Instr('movq', [Var('x'), Var('z')]),            # 5
            Instr('addq', [Var('w'), Var('z')]),            # 6
            Instr('movq', [Var('y'), Var('t')]),            # 7
            Instr('negq', [Var('t')]),                      # 8
            Instr('movq', [Var('z'), Reg('rax')]),          # 9
            Instr('addq', [Var('t'), Reg('rax')]),          # 10
            Jump('conclusion'),                              # 11
        ]
        cfg = single_block_cfg(instrs)
        la = analyze_liveness(cfg)['start']

        assert Var('v') in la[0]
        assert Var('w') not in la[0]

        assert Var('v') in la[1] and Var('w') in la[1]

        # After movq v, x: v is dead, w and x are live
        assert Var('v') not in la[2]
        assert Var('w') in la[2] and Var('x') in la[2]

        # After addq $7, x: w and x live
        assert Var('w') in la[3] and Var('x') in la[3]

        # After movq x, y: w, x, y live
        assert Var('w') in la[4] and Var('x') in la[4] and Var('y') in la[4]

        # After movq x, z: w, y, z live (x dead)
        assert Var('w') in la[5] and Var('y') in la[5] and Var('z') in la[5]
        assert Var('x') not in la[5]

        # After addq w, z: y, z live
        assert Var('y') in la[6] and Var('z') in la[6]
        assert Var('w') not in la[6]

        # After movq y, t: t, z live
        assert Var('t') in la[7] and Var('z') in la[7]

        # After negq t: t, z live
        assert Var('t') in la[8] and Var('z') in la[8]

        # After movq z, rax: t live (z dead)
        assert Var('t') in la[9]
        assert Var('z') not in la[9]

        # After addq t, rax: no vars live
        vars_in_10 = {loc for loc in la[10] if isinstance(loc, Var)}
        assert len(vars_in_10) == 0

    def test_branch_liveness(self):
        """Liveness through if-else branches merging at a join point."""
        start_instrs = [
            Instr('movq', [Immediate(5), Var('a')]),
            Instr('movq', [Immediate(10), Var('b')]),
            Instr('cmpq', [Var('a'), Var('b')]),
            JumpIf('l', 'then'),
            Jump('else'),
        ]
        then_instrs = [
            Instr('addq', [Var('a'), Var('b')]),
            Jump('end'),
        ]
        else_instrs = [
            Instr('addq', [Var('b'), Var('a')]),
            Jump('end'),
        ]
        end_instrs = [
            Instr('movq', [Var('a'), Reg('rax')]),
            Instr('addq', [Var('b'), Reg('rax')]),
            Jump('conclusion'),
        ]
        blocks = {
            'start': BasicBlock('start', start_instrs),
            'then': BasicBlock('then', then_instrs),
            'else': BasicBlock('else', else_instrs),
            'end': BasicBlock('end', end_instrs),
        }
        cfg = CFG(entry='start', blocks=blocks)
        la = analyze_liveness(cfg)

        then_la = la['then']
        assert Var('a') in then_la[-1] or Var('b') in then_la[-1]

        end_la = la['end']
        assert Var('b') in end_la[0]

    def test_loop_fixed_point(self):
        """Loop requires multiple iterations for liveness to converge."""
        header = [
            Instr('movq', [Immediate(0), Var('sum')]),
            Instr('movq', [Immediate(1), Var('i')]),
            Jump('loop'),
        ]
        loop_block = [
            Instr('cmpq', [Immediate(100), Var('i')]),
            JumpIf('l', 'body'),
            Jump('exit'),
        ]
        body_block = [
            Instr('addq', [Var('i'), Var('sum')]),
            Instr('addq', [Immediate(1), Var('i')]),
            Jump('loop'),
        ]
        exit_block = [
            Instr('movq', [Var('sum'), Reg('rax')]),
            Jump('conclusion'),
        ]
        blocks = {
            'header': BasicBlock('header', header),
            'loop': BasicBlock('loop', loop_block),
            'body': BasicBlock('body', body_block),
            'exit': BasicBlock('exit', exit_block),
        }
        cfg = CFG(entry='header', blocks=blocks)
        la = analyze_liveness(cfg)

        loop_la = la['loop']
        assert Var('i') in loop_la[0], "i must be live after cmpq in loop"
        assert Var('sum') in loop_la[0], "sum must be live after cmpq in loop"


# ──────────────────────────────────────────────────────────────────────
# 2. INTERFERENCE GRAPH TESTS
# ──────────────────────────────────────────────────────────────────────

class TestInterference:

    def test_straight_line_interference(self):
        """Verify interference edges."""
        instrs = [
            Instr('movq', [Immediate(1), Var('v')]),
            Instr('movq', [Immediate(42), Var('w')]),
            Instr('movq', [Var('v'), Var('x')]),
            Instr('addq', [Immediate(7), Var('x')]),
            Instr('movq', [Var('x'), Var('y')]),
            Instr('movq', [Var('x'), Var('z')]),
            Instr('addq', [Var('w'), Var('z')]),
            Instr('movq', [Var('y'), Var('t')]),
            Instr('negq', [Var('t')]),
            Instr('movq', [Var('z'), Reg('rax')]),
            Instr('addq', [Var('t'), Reg('rax')]),
            Jump('conclusion'),
        ]
        cfg = single_block_cfg(instrs)
        la = analyze_liveness(cfg)
        ig, mg = build_interference(cfg, la)

        def has_edge(g, a, b):
            return b in g.get(a, set())

        assert has_edge(ig, Var('w'), Var('v')), "w-v should interfere"
        assert has_edge(ig, Var('x'), Var('w')), "x-w should interfere"
        assert has_edge(ig, Var('y'), Var('w')), "y-w should interfere"
        assert has_edge(ig, Var('z'), Var('w')), "z-w should interfere"
        assert has_edge(ig, Var('z'), Var('y')), "z-y should interfere"
        assert has_edge(ig, Var('t'), Var('z')), "t-z should interfere"

        assert has_edge(mg, Var('v'), Var('x')), "v-x should be in move graph"
        assert has_edge(mg, Var('x'), Var('y')), "x-y should be in move graph"
        assert has_edge(mg, Var('x'), Var('z')), "x-z should be in move graph"
        assert has_edge(mg, Var('y'), Var('t')), "y-t should be in move graph"

    def test_no_self_interference(self):
        """negq x should not create a self-edge for x."""
        instrs = [
            Instr('movq', [Immediate(5), Var('x')]),
            Instr('negq', [Var('x')]),
            Instr('movq', [Var('x'), Reg('rax')]),
            Jump('conclusion'),
        ]
        cfg = single_block_cfg(instrs)
        la = analyze_liveness(cfg)
        ig, _ = build_interference(cfg, la)
        assert Var('x') not in ig.get(Var('x'), set()), "No self-edges"

    def test_move_no_interference(self):
        """movq x, y should NOT create an interference edge x-y."""
        instrs = [
            Instr('movq', [Immediate(1), Var('x')]),
            Instr('movq', [Var('x'), Var('y')]),
            Instr('movq', [Var('y'), Reg('rax')]),
            Jump('conclusion'),
        ]
        cfg = single_block_cfg(instrs)
        la = analyze_liveness(cfg)
        ig, _ = build_interference(cfg, la)

        assert Var('y') not in ig.get(Var('x'), set()), \
            "x-y should not interfere due to move rule"

    def test_call_clobbers_caller_save(self):
        """Callq should create interference between caller-save regs and live vars."""
        instrs = [
            Instr('movq', [Immediate(1), Var('x')]),
            Callq('some_func', 0),
            Instr('movq', [Var('x'), Reg('rax')]),
            Jump('conclusion'),
        ]
        cfg = single_block_cfg(instrs)
        la = analyze_liveness(cfg)
        ig, _ = build_interference(cfg, la)

        for rname in CALLER_SAVE_REGS:
            if rname in RESERVED_REGS:
                continue
            assert Reg(rname) in ig.get(Var('x'), set()), \
                f"x should interfere with caller-save reg {rname}"


# ──────────────────────────────────────────────────────────────────────
# 3. GRAPH COLORING TESTS
# ──────────────────────────────────────────────────────────────────────

class TestColoring:

    def test_simple_coloring(self):
        """Three-node path graph: should use at most 2 colors."""
        a, b, c = Var('a'), Var('b'), Var('c')
        verts = {a, b, c}
        ig = {a: {b}, b: {a, c}, c: {b}}
        mg = {a: set(), b: set(), c: set()}
        coloring = dsatur_color(verts, ig, mg, {})
        assert coloring[a] != coloring[b]
        assert coloring[b] != coloring[c]
        colors_used = set(coloring.values())
        assert len(colors_used) <= 2

    def test_precolored_respected(self):
        """Pre-colored vertices must keep their color."""
        a, b = Var('a'), Var('b')
        r = Reg('rcx')  # color 1
        verts = {a, b, r}
        ig = {a: {r, b}, b: {a, r}, r: {a, b}}
        mg = {a: set(), b: set(), r: set()}
        precolored = {r: REG_TO_COLOR['rcx']}
        coloring = dsatur_color(verts, ig, mg, precolored)
        assert coloring[r] == REG_TO_COLOR['rcx'], "Pre-colored reg must keep color"
        assert coloring[a] != coloring[r]
        assert coloring[b] != coloring[r]
        assert coloring[a] != coloring[b]

    def test_move_biasing(self):
        """Move biasing should prefer to give a variable the same color as its move partner."""
        a, b, c = Var('a'), Var('b'), Var('c')
        verts = {a, b, c}
        ig = {a: {c}, b: {c}, c: {a, b}}
        mg = {a: {b}, b: {a}, c: set()}
        coloring = dsatur_color(verts, ig, mg, {})
        assert coloring[a] == coloring[b], \
            "Move biasing should assign same color to move-related non-interfering vars"
        assert coloring[a] != coloring[c]

    def test_spill_to_stack(self):
        """When more than 12 colors needed, spill to stack (color >= 12)."""
        vs = [Var(f'v{i}') for i in range(14)]
        verts = set(vs)
        ig = {v: set() for v in vs}
        for i in range(len(vs)):
            for j in range(i+1, len(vs)):
                ig[vs[i]].add(vs[j])
                ig[vs[j]].add(vs[i])
        mg = {v: set() for v in vs}
        coloring = dsatur_color(verts, ig, mg, {})
        colors = set(coloring.values())
        assert len(colors) == 14, "14-clique needs 14 colors"
        spilled = [c for c in colors if c >= 12]
        assert len(spilled) >= 2, "At least 2 variables should spill (colors >= 12)"


# ──────────────────────────────────────────────────────────────────────
# 4. FULL PIPELINE INTEGRATION TESTS
# ──────────────────────────────────────────────────────────────────────

class TestFullPipeline:

    def _validate_allocation(self, cfg):
        """Run the full pipeline and verify the allocation is valid."""
        la = analyze_liveness(cfg)
        ig, mg = build_interference(cfg, la)

        all_locs = set()
        for block in cfg.blocks.values():
            for instr in block.instrs:
                all_locs |= reads_of(instr)
                all_locs |= writes_of(instr)
        all_locs = {loc for loc in all_locs
                    if not (isinstance(loc, Reg) and loc.name in RESERVED_REGS)}
        precolored = {}
        for loc in all_locs:
            if isinstance(loc, Reg) and loc.name in REG_TO_COLOR:
                precolored[loc] = REG_TO_COLOR[loc.name]

        coloring = dsatur_color(all_locs, ig, mg, precolored)

        for loc, neighbors in ig.items():
            for neighbor in neighbors:
                if loc in coloring and neighbor in coloring:
                    assert coloring[loc] != coloring[neighbor], \
                        f"Conflict: {loc}(c={coloring[loc]}) vs {neighbor}(c={coloring[neighbor]})"

        for loc, expected_color in precolored.items():
            assert coloring.get(loc) == expected_color, \
                f"Precolored {loc} should be {expected_color}, got {coloring.get(loc)}"

        return coloring

    def test_textbook_straight_line(self):
        instrs = [
            Instr('movq', [Immediate(1), Var('v')]),
            Instr('movq', [Immediate(42), Var('w')]),
            Instr('movq', [Var('v'), Var('x')]),
            Instr('addq', [Immediate(7), Var('x')]),
            Instr('movq', [Var('x'), Var('y')]),
            Instr('movq', [Var('x'), Var('z')]),
            Instr('addq', [Var('w'), Var('z')]),
            Instr('movq', [Var('y'), Var('t')]),
            Instr('negq', [Var('t')]),
            Instr('movq', [Var('z'), Reg('rax')]),
            Instr('addq', [Var('t'), Reg('rax')]),
            Jump('conclusion'),
        ]
        cfg = single_block_cfg(instrs)
        coloring = self._validate_allocation(cfg)
        var_colors = {loc: c for loc, c in coloring.items() if isinstance(loc, Var)}
        assert all(c < 12 for c in var_colors.values()), "No spills expected"

    def test_branch_program(self):
        start = [
            Instr('movq', [Immediate(10), Var('x')]),
            Instr('movq', [Immediate(20), Var('y')]),
            Instr('cmpq', [Var('x'), Var('y')]),
            JumpIf('l', 'then'),
            Jump('else'),
        ]
        then_blk = [
            Instr('movq', [Var('y'), Var('result')]),
            Jump('end'),
        ]
        else_blk = [
            Instr('movq', [Var('x'), Var('result')]),
            Jump('end'),
        ]
        end_blk = [
            Instr('movq', [Var('result'), Reg('rax')]),
            Jump('conclusion'),
        ]
        blocks = {
            'start': BasicBlock('start', start),
            'then': BasicBlock('then', then_blk),
            'else': BasicBlock('else', else_blk),
            'end': BasicBlock('end', end_blk),
        }
        cfg = CFG(entry='start', blocks=blocks)
        self._validate_allocation(cfg)

    def test_loop_program(self):
        header = [
            Instr('movq', [Immediate(0), Var('sum')]),
            Instr('movq', [Immediate(1), Var('i')]),
            Jump('loop'),
        ]
        loop_block = [
            Instr('cmpq', [Immediate(100), Var('i')]),
            JumpIf('l', 'body'),
            Jump('exit'),
        ]
        body_block = [
            Instr('addq', [Var('i'), Var('sum')]),
            Instr('addq', [Immediate(1), Var('i')]),
            Jump('loop'),
        ]
        exit_block = [
            Instr('movq', [Var('sum'), Reg('rax')]),
            Jump('conclusion'),
        ]
        blocks = {
            'header': BasicBlock('header', header),
            'loop': BasicBlock('loop', loop_block),
            'body': BasicBlock('body', body_block),
            'exit': BasicBlock('exit', exit_block),
        }
        cfg = CFG(entry='header', blocks=blocks)
        self._validate_allocation(cfg)

    def test_nested_loop_many_vars(self):
        """Complex program with nested loops and many variables."""
        init = [
            Instr('movq', [Immediate(0), Var('a')]),
            Instr('movq', [Immediate(1), Var('b')]),
            Instr('movq', [Immediate(2), Var('c')]),
            Instr('movq', [Immediate(3), Var('d')]),
            Instr('movq', [Immediate(4), Var('e')]),
            Instr('movq', [Immediate(0), Var('i')]),
            Jump('outer_test'),
        ]
        outer_test = [
            Instr('cmpq', [Immediate(10), Var('i')]),
            JumpIf('l', 'outer_body'),
            Jump('done'),
        ]
        outer_body = [
            Instr('movq', [Immediate(0), Var('j')]),
            Jump('inner_test'),
        ]
        inner_test = [
            Instr('cmpq', [Immediate(5), Var('j')]),
            JumpIf('l', 'inner_body'),
            Jump('outer_inc'),
        ]
        inner_body = [
            Instr('movq', [Var('a'), Var('tmp1')]),
            Instr('addq', [Var('b'), Var('tmp1')]),
            Instr('movq', [Var('c'), Var('tmp2')]),
            Instr('addq', [Var('d'), Var('tmp2')]),
            Instr('movq', [Var('tmp1'), Var('tmp3')]),
            Instr('addq', [Var('tmp2'), Var('tmp3')]),
            Instr('addq', [Var('tmp3'), Var('e')]),
            Instr('movq', [Var('b'), Var('a')]),
            Instr('movq', [Var('c'), Var('b')]),
            Instr('movq', [Var('d'), Var('c')]),
            Instr('movq', [Var('e'), Var('d')]),
            Instr('addq', [Immediate(1), Var('j')]),
            Jump('inner_test'),
        ]
        outer_inc = [
            Instr('addq', [Immediate(1), Var('i')]),
            Jump('outer_test'),
        ]
        done = [
            Instr('movq', [Var('e'), Reg('rax')]),
            Jump('conclusion'),
        ]
        blocks = {
            'init': BasicBlock('init', init),
            'outer_test': BasicBlock('outer_test', outer_test),
            'outer_body': BasicBlock('outer_body', outer_body),
            'inner_test': BasicBlock('inner_test', inner_test),
            'inner_body': BasicBlock('inner_body', inner_body),
            'outer_inc': BasicBlock('outer_inc', outer_inc),
            'done': BasicBlock('done', done),
        }
        cfg = CFG(entry='init', blocks=blocks)
        coloring = self._validate_allocation(cfg)
        prog_vars = cfg.all_variables()
        for vname in prog_vars:
            assert Var(vname) in coloring, f"Variable {vname} must be colored"

    def test_call_with_live_across(self):
        """Variables live across a call must not be in caller-save registers."""
        instrs = [
            Instr('movq', [Immediate(42), Var('x')]),
            Instr('movq', [Immediate(7), Var('y')]),
            Callq('some_func', 0),
            Instr('addq', [Var('x'), Var('y')]),
            Instr('movq', [Var('y'), Reg('rax')]),
            Jump('conclusion'),
        ]
        cfg = single_block_cfg(instrs)
        coloring = self._validate_allocation(cfg)
        caller_save_colors = {REG_TO_COLOR[r] for r in CALLER_SAVE_REGS
                              if r in REG_TO_COLOR}
        x_color = coloring[Var('x')]
        y_color = coloring[Var('y')]
        assert x_color not in caller_save_colors, \
            f"x (color {x_color}) must not be caller-save (lives across call)"
        assert y_color not in caller_save_colors, \
            f"y (color {y_color}) must not be caller-save (lives across call)"

    def test_diamond_cfg(self):
        """Diamond-shaped CFG: entry -> {A, B} -> exit."""
        entry = [
            Instr('movq', [Immediate(1), Var('p')]),
            Instr('movq', [Immediate(2), Var('q')]),
            Instr('movq', [Immediate(3), Var('r')]),
            Instr('cmpq', [Var('p'), Var('q')]),
            JumpIf('l', 'left'),
            Jump('right'),
        ]
        left = [
            Instr('addq', [Var('p'), Var('r')]),
            Instr('movq', [Var('r'), Var('s')]),
            Jump('merge'),
        ]
        right = [
            Instr('addq', [Var('q'), Var('r')]),
            Instr('movq', [Var('r'), Var('s')]),
            Jump('merge'),
        ]
        merge = [
            Instr('addq', [Var('p'), Var('s')]),
            Instr('movq', [Var('s'), Reg('rax')]),
            Jump('conclusion'),
        ]
        blocks = {
            'entry': BasicBlock('entry', entry),
            'left': BasicBlock('left', left),
            'right': BasicBlock('right', right),
            'merge': BasicBlock('merge', merge),
        }
        cfg = CFG(entry='entry', blocks=blocks)
        self._validate_allocation(cfg)

    def test_many_interferences_force_spill(self):
        """Force spilling by creating many simultaneously live variables."""
        instrs = []
        var_names = [f'v{i}' for i in range(15)]
        for i, name in enumerate(var_names):
            instrs.append(Instr('movq', [Immediate(i + 1), Var(name)]))
        for i in range(len(var_names) - 1):
            instrs.append(Instr('addq', [Var(var_names[i]), Var(var_names[i+1])]))
        instrs.append(Instr('movq', [Var(var_names[-1]), Reg('rax')]))
        instrs.append(Jump('conclusion'))

        cfg = single_block_cfg(instrs)
        coloring = self._validate_allocation(cfg)
        var_colors = {loc: c for loc, c in coloring.items() if isinstance(loc, Var)}
        spilled = sum(1 for c in var_colors.values() if c >= 12)
        assert spilled >= 3, f"Expected >= 3 spills, got {spilled}"


# ──────────────────────────────────────────────────────────────────────
# 5. END-TO-END CODE GENERATION TESTS
#    Compile generated assembly with gcc, run, check output.
# ──────────────────────────────────────────────────────────────────────

class TestEndToEnd:

    def _compile_and_run(self, cfg, expected_output):
        """Allocate registers, generate assembly, compile with gcc, run, check."""
        alloc = allocate_registers(cfg)
        asm_text = emit_x86(cfg, alloc)

        with tempfile.TemporaryDirectory() as tmpdir:
            asm_path = os.path.join(tmpdir, 'program.s')
            exe_path = os.path.join(tmpdir, 'program')

            with open(asm_path, 'w') as f:
                f.write(asm_text)

            # Compile
            result = subprocess.run(
                ['gcc', '-no-pie', '-o', exe_path, asm_path, '/app/main.c'],
                capture_output=True, text=True
            )
            assert result.returncode == 0, \
                f"gcc compilation failed:\n{result.stderr}\n--- Assembly ---\n{asm_text}"

            # Run
            result = subprocess.run(
                [exe_path], capture_output=True, text=True, timeout=10
            )
            assert result.returncode == 0, \
                f"Program crashed (exit {result.returncode}):\n{result.stderr}\n--- Assembly ---\n{asm_text}"

            actual = result.stdout.strip()
            assert actual == str(expected_output), \
                f"Expected {expected_output}, got '{actual}'\n--- Assembly ---\n{asm_text}"

    def test_e2e_arithmetic(self):
        """Straight-line: v=1, w=42, x=v+7=8, y=x, z=x+w=50, t=-y=-8, rax=z+t=42."""
        instrs = [
            Instr('movq', [Immediate(1), Var('v')]),
            Instr('movq', [Immediate(42), Var('w')]),
            Instr('movq', [Var('v'), Var('x')]),
            Instr('addq', [Immediate(7), Var('x')]),
            Instr('movq', [Var('x'), Var('y')]),
            Instr('movq', [Var('x'), Var('z')]),
            Instr('addq', [Var('w'), Var('z')]),
            Instr('movq', [Var('y'), Var('t')]),
            Instr('negq', [Var('t')]),
            Instr('movq', [Var('z'), Reg('rax')]),
            Instr('addq', [Var('t'), Reg('rax')]),
            Jump('conclusion'),
        ]
        cfg = single_block_cfg(instrs)
        self._compile_and_run(cfg, 42)

    def test_e2e_loop(self):
        """Sum 1..99 = 4950."""
        header = [
            Instr('movq', [Immediate(0), Var('sum')]),
            Instr('movq', [Immediate(1), Var('i')]),
            Jump('loop'),
        ]
        loop_block = [
            Instr('cmpq', [Immediate(100), Var('i')]),
            JumpIf('l', 'body'),
            Jump('exit'),
        ]
        body_block = [
            Instr('addq', [Var('i'), Var('sum')]),
            Instr('addq', [Immediate(1), Var('i')]),
            Jump('loop'),
        ]
        exit_block = [
            Instr('movq', [Var('sum'), Reg('rax')]),
            Jump('conclusion'),
        ]
        blocks = {
            'header': BasicBlock('header', header),
            'loop': BasicBlock('loop', loop_block),
            'body': BasicBlock('body', body_block),
            'exit': BasicBlock('exit', exit_block),
        }
        cfg = CFG(entry='header', blocks=blocks)
        self._compile_and_run(cfg, 4950)

    def test_e2e_branch(self):
        """max(5, 13) = 13 via conditional branch."""
        start = [
            Instr('movq', [Immediate(5), Var('a')]),
            Instr('movq', [Immediate(13), Var('b')]),
            Instr('cmpq', [Var('a'), Var('b')]),
            JumpIf('l', 'take_a'),
            Jump('take_b'),
        ]
        take_a = [
            Instr('movq', [Var('a'), Reg('rax')]),
            Jump('conclusion'),
        ]
        take_b = [
            Instr('movq', [Var('b'), Reg('rax')]),
            Jump('conclusion'),
        ]
        blocks = {
            'start': BasicBlock('start', start),
            'take_a': BasicBlock('take_a', take_a),
            'take_b': BasicBlock('take_b', take_b),
        }
        cfg = CFG(entry='start', blocks=blocks)
        # cmpq a, b → computes b - a = 8 > 0 → jl (b < a) not taken → take_b
        self._compile_and_run(cfg, 13)

    def test_e2e_spill(self):
        """15 simultaneously live vars → at least 3 must spill to stack."""
        instrs = []
        var_names = [f'v{i}' for i in range(15)]
        for i, name in enumerate(var_names):
            instrs.append(Instr('movq', [Immediate(i + 1), Var(name)]))
        # Chain: v1 += v0, v2 += v1, ..., v14 += v13
        for i in range(len(var_names) - 1):
            instrs.append(Instr('addq', [Var(var_names[i]), Var(var_names[i+1])]))
        instrs.append(Instr('movq', [Var(var_names[-1]), Reg('rax')]))
        instrs.append(Jump('conclusion'))

        cfg = single_block_cfg(instrs)
        # Expected: v0=1..v14=15, then v1+=v0=3, v2+=v1=6, ..., v14=120
        self._compile_and_run(cfg, 120)

    def test_e2e_nested_loop(self):
        """Nested loops with many variables — tests complex control flow codegen."""
        init = [
            Instr('movq', [Immediate(0), Var('a')]),
            Instr('movq', [Immediate(1), Var('b')]),
            Instr('movq', [Immediate(2), Var('c')]),
            Instr('movq', [Immediate(3), Var('d')]),
            Instr('movq', [Immediate(4), Var('e')]),
            Instr('movq', [Immediate(0), Var('i')]),
            Jump('outer_test'),
        ]
        outer_test = [
            Instr('cmpq', [Immediate(3), Var('i')]),
            JumpIf('l', 'outer_body'),
            Jump('done'),
        ]
        outer_body = [
            Instr('movq', [Immediate(0), Var('j')]),
            Jump('inner_test'),
        ]
        inner_test = [
            Instr('cmpq', [Immediate(2), Var('j')]),
            JumpIf('l', 'inner_body'),
            Jump('outer_inc'),
        ]
        inner_body = [
            Instr('movq', [Var('a'), Var('tmp1')]),
            Instr('addq', [Var('b'), Var('tmp1')]),
            Instr('movq', [Var('c'), Var('tmp2')]),
            Instr('addq', [Var('d'), Var('tmp2')]),
            Instr('movq', [Var('tmp1'), Var('tmp3')]),
            Instr('addq', [Var('tmp2'), Var('tmp3')]),
            Instr('addq', [Var('tmp3'), Var('e')]),
            Instr('movq', [Var('b'), Var('a')]),
            Instr('movq', [Var('c'), Var('b')]),
            Instr('movq', [Var('d'), Var('c')]),
            Instr('movq', [Var('e'), Var('d')]),
            Instr('addq', [Immediate(1), Var('j')]),
            Jump('inner_test'),
        ]
        outer_inc = [
            Instr('addq', [Immediate(1), Var('i')]),
            Jump('outer_test'),
        ]
        done = [
            Instr('movq', [Var('e'), Reg('rax')]),
            Jump('conclusion'),
        ]
        blocks = {
            'init': BasicBlock('init', init),
            'outer_test': BasicBlock('outer_test', outer_test),
            'outer_body': BasicBlock('outer_body', outer_body),
            'inner_test': BasicBlock('inner_test', inner_test),
            'inner_body': BasicBlock('inner_body', inner_body),
            'outer_inc': BasicBlock('outer_inc', outer_inc),
            'done': BasicBlock('done', done),
        }
        cfg = CFG(entry='init', blocks=blocks)
        # 3 outer × 2 inner iterations of generalized Fibonacci → e = 1164
        self._compile_and_run(cfg, 1164)
