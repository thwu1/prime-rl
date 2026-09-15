"""
Tests for RTL Compiler Optimizer.


Verifies semantic preservation, optimization effectiveness, and build artifacts.
"""

import pytest
import sys
import os
import subprocess
import random

sys.path.insert(0, '/app')
from rtl import load_program, interpret

try:
    from optimizer import optimize
except ImportError:
    pytest.skip("optimizer.py not found at /app/optimizer.py", allow_module_level=True)

PROGRAMS_DIR = '/app/programs'
PROGRAM_NAMES = ['poly_eval', 'const_arith', 'dead_triangle', 'branch_const',
                 'cascade', 'loop_constprop', 'nested_diamond', 'strength_chain']


def load(name):
    return load_program(os.path.join(PROGRAMS_DIR, f'{name}.json'))


def get_successors(instr):
    kind = instr["kind"]
    if kind == "nop":
        return [instr["succ"]]
    elif kind == "op":
        return [instr["succ"]]
    elif kind == "cond":
        return [instr["ifso"], instr["ifnot"]]
    elif kind == "ret":
        return []
    return []


def get_reachable(prog):
    code = prog["code"]
    entry = prog["entrypoint"]
    visited = set()
    queue = [entry]
    while queue:
        n = queue.pop(0)
        if n in visited or n not in code:
            continue
        visited.add(n)
        for s in get_successors(code[n]):
            if s not in visited:
                queue.append(s)
    return visited


def count_computation_ops(prog):
    """Count non-trivial computation instructions (not const/move/nop) in reachable code."""
    reachable = get_reachable(prog)
    count = 0
    for n in reachable:
        instr = prog["code"][n]
        if instr["kind"] == "op" and instr["op"] not in ("const", "move"):
            count += 1
    return count


# === Test data: (args, expected_output) for each program ===

TEST_CASES = {
    'poly_eval': [
        ([5], 51), ([0], 6), ([10], 146), ([-1], 3), ([100], 10406),
        ([7], 83), ([-5], 11),
    ],
    'const_arith': [
        ([5], 40), ([0], 0), ([3], 24), ([10], 80), ([-5], -40),
        ([1], 8), ([12], 96),
    ],
    'dead_triangle': [
        ([5, 3], 8), ([0, 0], 0), ([10, 7], 17), ([-3, 5], 2),
        ([1, -1], 0), ([100, 200], 300),
    ],
    'branch_const': [
        ([5], 15), ([0], 10), ([100], 110), ([-10], 0),
        ([42], 52), ([-100], -90),
    ],
    'cascade': [
        ([3, 4], 56), ([0, 0], 0), ([1, 1], 6), ([5, 2], 56),
        ([10, 10], 420), ([2, 3], 30),
    ],
    'loop_constprop': [
        ([5], 55), ([3], 14), ([0], 0), ([1], 1), ([10], 385),
        ([4], 30), ([7], 140),
    ],
    'nested_diamond': [
        ([5, 3], 30), ([0, 3], -3), ([1, 1], 2), ([-2, 4], -20),
        ([3, -2], -12), ([10, 10], 200), ([-1, 5], -15),
    ],
    'strength_chain': [
        ([5], 5), ([0], 0), ([-7], -7), ([100], 100),
        ([42], 42), ([1], 1), ([-100], -100),
    ],
}


# === Semantic Preservation Tests ===

class TestSemanticPreservation:
    """Optimized programs must produce identical outputs to originals."""

    @pytest.mark.parametrize("name", PROGRAM_NAMES)
    def test_outputs_match(self, name):
        prog = load(name)
        opt_prog = optimize(prog)

        for args, expected in TEST_CASES[name]:
            orig = interpret(prog, args)
            assert orig == expected, f"Original {name}({args}): expected {expected}, got {orig}"

            opt = interpret(opt_prog, args)
            assert opt == expected, (
                f"Optimized {name}({args}): expected {expected}, got {opt}"
            )


# === Optimization Quality Tests ===

class TestOptimizationQuality:
    """Optimizer must measurably reduce computation instructions."""

    @pytest.mark.parametrize("name,min_reduction", [
        ('poly_eval', 2),
        ('const_arith', 3),
        ('dead_triangle', 3),
        ('cascade', 3),
        ('loop_constprop', 1),
        ('nested_diamond', 2),
        ('strength_chain', 3),
    ])
    def test_computation_reduction(self, name, min_reduction):
        prog = load(name)
        opt_prog = optimize(prog)

        orig_count = count_computation_ops(prog)
        opt_count = count_computation_ops(opt_prog)
        reduction = orig_count - opt_count

        assert reduction >= min_reduction, (
            f"{name}: need >= {min_reduction} fewer computation ops, "
            f"got {reduction} (orig={orig_count}, opt={opt_count})"
        )

    def test_const_arith_max_ops(self):
        prog = load('const_arith')
        opt_prog = optimize(prog)
        comp = count_computation_ops(opt_prog)
        assert comp <= 3, (
            f"const_arith: expected <= 3 computation ops after optimization, got {comp}"
        )

    def test_dead_triangle_max_ops(self):
        prog = load('dead_triangle')
        opt_prog = optimize(prog)
        comp = count_computation_ops(opt_prog)
        assert comp <= 2, (
            f"dead_triangle: expected <= 2 computation ops after optimization, got {comp}"
        )


# === Pattern-Specific Tests ===

class TestPatternSpecific:
    """Tests for specific optimization patterns."""

    def test_branch_const_node19_unreachable(self):
        """Node 19 in branch_const must become unreachable."""
        prog = load('branch_const')
        opt_prog = optimize(prog)

        reachable = get_reachable(opt_prog)
        assert 19 not in reachable, (
            "branch_const: node 19 (false branch) should be unreachable "
            "after optimization resolves the constant conditional"
        )

    def test_poly_eval_redundant_add(self):
        """At most 1 add(r1,r2) should remain in poly_eval."""
        prog = load('poly_eval')
        opt_prog = optimize(prog)

        reachable = get_reachable(opt_prog)
        add_r1_r2_count = 0
        for n in reachable:
            instr = opt_prog["code"][n]
            if (instr["kind"] == "op" and instr["op"] == "add"
                    and sorted(instr.get("args", [])) == [1, 2]):
                add_r1_r2_count += 1

        assert add_r1_r2_count <= 1, (
            f"poly_eval: found {add_r1_r2_count} add(r1,r2) instructions, "
            f"expected <= 1 (original has 3)"
        )

    def test_loop_constprop_redundant_add(self):
        """At most 2 add(r3,r4) should remain in loop_constprop."""
        prog = load('loop_constprop')
        opt_prog = optimize(prog)

        reachable = get_reachable(opt_prog)
        add_r3_r4_count = 0
        for n in reachable:
            instr = opt_prog["code"][n]
            if (instr["kind"] == "op" and instr["op"] == "add"
                    and sorted(instr.get("args", [])) == [3, 4]):
                add_r3_r4_count += 1

        assert add_r3_r4_count <= 2, (
            f"loop_constprop: found {add_r3_r4_count} add(r3,r4) instructions, "
            f"expected <= 2 (original has 3)"
        )

    def test_cascade_multi_pass(self):
        """Cascade must achieve >= 3 reduction and preserve semantics broadly."""
        prog = load('cascade')
        opt_prog = optimize(prog)

        orig_comp = count_computation_ops(prog)
        opt_comp = count_computation_ops(opt_prog)

        assert orig_comp - opt_comp >= 3, (
            f"cascade: should reduce >= 3 computation ops, "
            f"got {orig_comp - opt_comp} (orig={orig_comp}, opt={opt_comp})"
        )

        for x in range(-5, 10):
            for y in range(-3, 5):
                orig = interpret(prog, [x, y])
                opt = interpret(opt_prog, [x, y])
                assert orig == opt, (
                    f"cascade({x},{y}): orig={orig}, opt={opt}"
                )

    def test_strength_chain_wide_range(self):
        """strength_chain must preserve semantics across a wide input range."""
        prog = load('strength_chain')
        opt_prog = optimize(prog)

        for x in range(-50, 51):
            orig = interpret(prog, [x])
            opt = interpret(opt_prog, [x])
            assert orig == opt, (
                f"strength_chain({x}): orig={orig}, opt={opt}"
            )

    def test_nested_diamond_both_branches(self):
        """nested_diamond must preserve semantics on both branches."""
        prog = load('nested_diamond')
        opt_prog = optimize(prog)

        for x in range(-10, 11):
            for y in range(-5, 6):
                orig = interpret(prog, [x, y])
                opt = interpret(opt_prog, [x, y])
                assert orig == opt, (
                    f"nested_diamond({x},{y}): orig={orig}, opt={opt}"
                )


# === Fuzz Testing ===

class TestFuzzCorrectness:
    """Stress-test optimizer correctness on randomly generated programs."""

    @staticmethod
    def _gen_program(seed, n_nodes=12, n_params=2):
        """Generate a deterministic random RTL program (acyclic, always terminates)."""
        rng = random.Random(seed)
        params = list(range(1, n_params + 1))
        next_reg = n_params + 1
        nodes = list(range(100, 100 + n_nodes))
        code = {}

        for i, nid in enumerate(nodes):
            if i == len(nodes) - 1:
                avail = params + list(range(n_params + 1, next_reg))
                code[nid] = {"kind": "ret",
                             "arg": rng.choice(avail) if avail else 1}
                continue

            succ = nodes[i + 1]

            if rng.random() < 0.12 and 0 < i < len(nodes) - 2:
                avail = params + list(range(n_params + 1, next_reg))
                if len(avail) >= 2:
                    a, b = rng.sample(avail, 2)
                    later = nodes[i + 2:]
                    ifnot = rng.choice(later)
                    code[nid] = {
                        "kind": "cond",
                        "cmp": rng.choice(["eq", "ne", "lt", "le", "gt", "ge"]),
                        "arg1": a, "arg2": b,
                        "ifso": succ, "ifnot": ifnot
                    }
                    continue

            choices = ["const", "const", "add", "sub", "mul", "move", "nop"]
            pick = rng.choice(choices)
            avail = params + list(range(n_params + 1, next_reg))

            if pick == "const":
                code[nid] = {"kind": "op", "op": "const",
                             "imm": rng.randint(-10, 10),
                             "args": [], "dst": next_reg, "succ": succ}
                next_reg += 1
            elif pick == "move" and avail:
                code[nid] = {"kind": "op", "op": "move",
                             "args": [rng.choice(avail)],
                             "dst": next_reg, "succ": succ}
                next_reg += 1
            elif pick in ("add", "sub", "mul") and avail:
                code[nid] = {"kind": "op", "op": pick,
                             "args": [rng.choice(avail), rng.choice(avail)],
                             "dst": next_reg, "succ": succ}
                next_reg += 1
            elif pick == "nop":
                code[nid] = {"kind": "nop", "succ": succ}
            else:
                code[nid] = {"kind": "op", "op": "const", "imm": 0,
                             "args": [], "dst": next_reg, "succ": succ}
                next_reg += 1

        return {"name": f"fuzz_{seed}", "params": params,
                "entrypoint": nodes[0], "code": code}

    @pytest.mark.parametrize("seed", range(40))
    def test_random_program_correctness(self, seed):
        """Optimizer must preserve semantics on arbitrary valid RTL programs."""
        prog = self._gen_program(seed, n_nodes=12, n_params=2)
        try:
            opt_prog = optimize(prog)
        except Exception as e:
            pytest.fail(f"Optimizer crashed on fuzz_{seed}: {e}")

        assert "code" in opt_prog
        assert "entrypoint" in opt_prog
        assert opt_prog["entrypoint"] in opt_prog["code"]

        rng = random.Random(seed + 5000)
        for _ in range(15):
            args = [rng.randint(-50, 50) for _ in prog["params"]]
            try:
                orig = interpret(prog, args)
            except RuntimeError:
                continue
            try:
                opt = interpret(opt_prog, args)
            except RuntimeError as e:
                pytest.fail(
                    f"Optimized fuzz_{seed}({args}) failed ({e}) "
                    f"but original returned {orig}"
                )
            assert orig == opt, f"fuzz_{seed}({args}): orig={orig}, opt={opt}"


# === Structural Validity Tests ===

class TestStructuralValidity:
    """Optimized programs must be structurally valid RTL."""

    @pytest.mark.parametrize("name", PROGRAM_NAMES)
    def test_valid_structure(self, name):
        prog = load(name)
        opt_prog = optimize(prog)

        assert "name" in opt_prog
        assert "params" in opt_prog
        assert "entrypoint" in opt_prog
        assert "code" in opt_prog
        assert opt_prog["entrypoint"] in opt_prog["code"], (
            f"{name}: entrypoint {opt_prog['entrypoint']} not in code"
        )

    @pytest.mark.parametrize("name", PROGRAM_NAMES)
    def test_successors_exist(self, name):
        """All successor references in reachable code must point to valid nodes."""
        prog = load(name)
        opt_prog = optimize(prog)

        reachable = get_reachable(opt_prog)
        code = opt_prog["code"]

        for n in reachable:
            instr = code[n]
            for s in get_successors(instr):
                assert s in code, (
                    f"{name}: node {n} references successor {s} not in code"
                )

    @pytest.mark.parametrize("name", PROGRAM_NAMES)
    def test_no_crash_on_varied_inputs(self, name):
        """Optimized programs must not crash on various inputs."""
        prog = load(name)
        opt_prog = optimize(prog)

        n_params = len(prog["params"])
        test_vals = [0, 1, -1, 5, 10, -10, 100]

        if n_params == 1:
            for v in test_vals:
                interpret(opt_prog, [v])
        elif n_params == 2:
            for v1 in test_vals[:4]:
                for v2 in test_vals[:4]:
                    interpret(opt_prog, [v1, v2])


# === Build Artifact Tests ===

class TestBuildArtifacts:
    """Makefile must produce optimized JSON files and SVG CFG visualizations."""

    def test_makefile_exists(self):
        assert os.path.exists('/app/Makefile'), "Makefile not found at /app/Makefile"

    def test_make_optimize_succeeds(self):
        result = subprocess.run(
            ['make', 'optimize'], cwd='/app',
            capture_output=True, timeout=120
        )
        assert result.returncode == 0, (
            f"make optimize failed: {result.stderr.decode()}"
        )

    def test_optimized_files_exist(self):
        subprocess.run(['make', 'optimize'], cwd='/app', capture_output=True, timeout=120)
        for name in PROGRAM_NAMES:
            path = f'/app/optimized/{name}.json'
            assert os.path.exists(path), f"Missing optimized file: {path}"

    def test_optimized_files_loadable(self):
        subprocess.run(['make', 'optimize'], cwd='/app', capture_output=True, timeout=120)
        for name in PROGRAM_NAMES:
            prog = load_program(f'/app/optimized/{name}.json')
            assert 'code' in prog
            assert 'entrypoint' in prog

    def test_make_render_succeeds(self):
        subprocess.run(['make', 'optimize'], cwd='/app', capture_output=True, timeout=120)
        result = subprocess.run(
            ['make', 'render'], cwd='/app',
            capture_output=True, timeout=120
        )
        assert result.returncode == 0, (
            f"make render failed: {result.stderr.decode()}"
        )

    def test_svg_files_exist(self):
        subprocess.run(['make', 'optimize'], cwd='/app', capture_output=True, timeout=120)
        subprocess.run(['make', 'render'], cwd='/app', capture_output=True, timeout=120)
        for name in PROGRAM_NAMES:
            for suffix in ['before', 'after']:
                path = f'/app/cfg_output/{name}_{suffix}.svg'
                assert os.path.exists(path), f"Missing SVG: {path}"

    def test_svg_files_valid(self):
        subprocess.run(['make', 'optimize'], cwd='/app', capture_output=True, timeout=120)
        subprocess.run(['make', 'render'], cwd='/app', capture_output=True, timeout=120)
        for name in PROGRAM_NAMES:
            for suffix in ['before', 'after']:
                path = f'/app/cfg_output/{name}_{suffix}.svg'
                if os.path.exists(path):
                    with open(path) as f:
                        content = f.read()
                    assert '<svg' in content, f"Invalid SVG (no <svg tag): {path}"
