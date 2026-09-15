"""
Local smoke tests for the register allocator and code generator.
Run: python3 /app/test_local.py
"""
import subprocess
from cfg import *
from allocator import allocate_registers
from liveness import analyze_liveness
from interference import build_interference
from coloring import dsatur_color


def make_straight_line_cfg():
    """
    Straight-line program:
      v = 1; w = 42; x = v + 7; y = x; z = x + w; result = z + (-y)
    """
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
    blocks = {'start': BasicBlock('start', instrs)}
    return CFG(entry='start', blocks=blocks)


def test_straight_line():
    cfg = make_straight_line_cfg()
    result = allocate_registers(cfg)
    print("Straight-line allocation:", result)
    for v in ['v', 'w', 'x', 'y', 'z', 't']:
        assert v in result, f"Variable {v} not allocated"
    print("  PASS: all variables allocated")

    live = analyze_liveness(cfg)
    ig, mg = build_interference(cfg, live)
    all_locs = set()
    for block in cfg.blocks.values():
        for instr in block.instrs:
            all_locs |= reads_of(instr)
            all_locs |= writes_of(instr)
    all_locs = {loc for loc in all_locs if not (isinstance(loc, Reg) and loc.name in RESERVED_REGS)}
    precolored = {}
    for loc in all_locs:
        if isinstance(loc, Reg) and loc.name in REG_TO_COLOR:
            precolored[loc] = REG_TO_COLOR[loc.name]
    coloring = dsatur_color(all_locs, ig, mg, precolored)

    for loc, neighbors in ig.items():
        for neighbor in neighbors:
            if loc in coloring and neighbor in coloring:
                assert coloring[loc] != coloring[neighbor], \
                    f"Interfering {loc} and {neighbor} share color {coloring[loc]}"
    print("  PASS: no interfering variables share a color")


def test_branch():
    """Program with an if-else branch."""
    start_instrs = [
        Instr('movq', [Immediate(10), Var('x')]),
        Instr('movq', [Immediate(20), Var('y')]),
        Instr('cmpq', [Var('x'), Var('y')]),
        JumpIf('l', 'then'),
        Jump('else'),
    ]
    then_instrs = [
        Instr('movq', [Var('y'), Var('z')]),
        Jump('end'),
    ]
    else_instrs = [
        Instr('movq', [Var('x'), Var('z')]),
        Jump('end'),
    ]
    end_instrs = [
        Instr('movq', [Var('z'), Reg('rax')]),
        Jump('conclusion'),
    ]
    blocks = {
        'start': BasicBlock('start', start_instrs),
        'then': BasicBlock('then', then_instrs),
        'else': BasicBlock('else', else_instrs),
        'end': BasicBlock('end', end_instrs),
    }
    cfg = CFG(entry='start', blocks=blocks)
    result = allocate_registers(cfg)
    print("Branch allocation:", result)
    for v in ['x', 'y', 'z']:
        assert v in result, f"Variable {v} not allocated"
    print("  PASS: branch test")


def test_loop():
    """Simple loop: i = 0; while i < 10: i = i + 1; return i"""
    header_instrs = [
        Instr('movq', [Immediate(0), Var('i')]),
        Jump('loop'),
    ]
    loop_instrs = [
        Instr('cmpq', [Immediate(10), Var('i')]),
        JumpIf('l', 'body'),
        Jump('exit'),
    ]
    body_instrs = [
        Instr('addq', [Immediate(1), Var('i')]),
        Jump('loop'),
    ]
    exit_instrs = [
        Instr('movq', [Var('i'), Reg('rax')]),
        Jump('conclusion'),
    ]
    blocks = {
        'header': BasicBlock('header', header_instrs),
        'loop': BasicBlock('loop', loop_instrs),
        'body': BasicBlock('body', body_instrs),
        'exit': BasicBlock('exit', exit_instrs),
    }
    cfg = CFG(entry='header', blocks=blocks)
    result = allocate_registers(cfg)
    print("Loop allocation:", result)
    assert 'i' in result
    print("  PASS: loop test")


def test_codegen():
    """End-to-end: generate assembly, compile with gcc, run."""
    try:
        from codegen import emit_x86
    except ImportError:
        print("  SKIP: codegen module not found")
        return

    cfg = make_straight_line_cfg()
    alloc = allocate_registers(cfg)
    try:
        asm = emit_x86(cfg, alloc)
    except NotImplementedError:
        print("  SKIP: codegen not implemented yet")
        return

    with open('/tmp/test_codegen.s', 'w') as f:
        f.write(asm)

    proc = subprocess.run(
        ['gcc', '-no-pie', '-o', '/tmp/test_codegen', '/tmp/test_codegen.s', '/app/main.c'],
        capture_output=True, text=True
    )
    assert proc.returncode == 0, f"gcc failed:\n{proc.stderr}\n{asm}"

    proc = subprocess.run(['/tmp/test_codegen'], capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0, f"Program crashed: {proc.stderr}"
    assert proc.stdout.strip() == '42', f"Expected 42, got {proc.stdout.strip()}"
    print("  PASS: codegen test (expected 42, got 42)")


if __name__ == '__main__':
    test_straight_line()
    test_branch()
    test_loop()
    test_codegen()
    print("\nAll local tests passed!")
