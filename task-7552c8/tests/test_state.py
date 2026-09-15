
import subprocess
import os
import pytest

SIM = "/app/sim86"
BIN_DIR = "/app/binaries"
TMP = "/tmp/sim86_tests"


@pytest.fixture(autouse=True)
def setup_tmp():
    os.makedirs(TMP, exist_ok=True)


def run_sim(bin_name, extra_args=None):
    """Run the simulator and return (regs_dict, flags_set, cycles)."""
    bp = os.path.join(BIN_DIR, bin_name)
    cmd = [SIM, bp]
    if extra_args:
        cmd.extend(extra_args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (
        f"Simulator exited {r.returncode} on {bin_name}:\n"
        f"stderr: {r.stderr}\nstdout: {r.stdout}"
    )
    return parse_output(r.stdout)


def run_sim_cycles(bin_name):
    """Run simulator in --cycles mode, return (list_of_tuples, total)."""
    bp = os.path.join(BIN_DIR, bin_name)
    cmd = [SIM, bp, "--cycles"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (
        f"Simulator --cycles exited {r.returncode} on {bin_name}:\n"
        f"stderr: {r.stderr}\nstdout: {r.stdout}"
    )
    entries = []
    total = None
    for line in r.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("TOTAL:"):
            total = int(line.split(":")[1])
        else:
            parts = line.split(",")
            if len(parts) == 5:
                entries.append(tuple(int(x) for x in parts))
    return entries, total


def parse_output(stdout):
    regs = {}
    flags = set()
    cycles = None
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if key == "flags":
            flags = set(f.upper() for f in val.split() if f)
        elif key == "cycles":
            cycles = int(val)
        else:
            try:
                regs[key] = int(val)
            except ValueError:
                pass
    return regs, flags, cycles


# ── Test 0: simulator exists and is executable ──


def test_simulator_exists():
    assert os.path.exists(SIM), f"Simulator not found at {SIM}"
    assert os.access(SIM, os.X_OK), f"{SIM} is not executable"


# ── Test 1: register moves and basic arithmetic ──


def test_regops():
    regs, flags, cycles = run_sim("prog_regops.bin")
    assert regs["ax"] == 3
    assert regs["bx"] == 2
    assert regs["cx"] == 2
    assert regs["dx"] == 4
    assert regs["sp"] == 100
    assert regs["bp"] == 200
    assert regs["si"] == 300
    assert regs["di"] == 400
    assert "ZF" not in flags
    assert "SF" not in flags
    assert cycles == 39, f"Expected 39 cycles, got {cycles}"


# ── Test 2: loop with arithmetic ──


def test_loops():
    regs, flags, cycles = run_sim("prog_loops.bin")
    assert regs["bx"] == 1030
    assert regs["cx"] == 0
    assert "ZF" in flags
    assert cycles == 68, f"Expected 68 cycles, got {cycles}"


# ── Test 3: memory read/write with EA costs ──


def test_memory():
    regs, flags, cycles = run_sim("prog_memory.bin")
    assert regs["ax"] == 6
    assert regs["bx"] == 1000
    assert cycles == 106, f"Expected 106 cycles, got {cycles}"


# ── Test 4: conditional branching ──


def test_conditionals():
    regs, flags, cycles = run_sim("prog_cond.bin")
    assert regs["ax"] == 10
    assert regs["bx"] == 10
    assert regs["cx"] == 10
    assert "ZF" not in flags
    assert "SF" not in flags
    assert cycles == 24, f"Expected 24 cycles, got {cycles}"


# ── Test 5: rectangle drawing into memory ──


def test_rectangle():
    memdump = os.path.join(TMP, "rect_mem.bin")
    regs, flags, cycles = run_sim(
        "prog_rect.bin", ["--memdump", memdump, "64", "256"]
    )
    assert regs["bp"] == 320
    assert regs["dx"] == 8
    assert regs["cx"] == 8
    assert "ZF" in flags
    assert cycles == 5436, f"Expected 5436 cycles, got {cycles}"

    assert os.path.exists(memdump), "Memory dump file not created"
    with open(memdump, "rb") as f:
        mem = f.read()
    assert len(mem) == 256, f"Expected 256 bytes, got {len(mem)}"

    for y in range(8):
        for x in range(8):
            off = (y * 8 + x) * 4
            assert mem[off] == x, (
                f"Pixel ({x},{y}) byte 0: expected {x}, got {mem[off]}"
            )
            assert mem[off + 1] == 0, (
                f"Pixel ({x},{y}) byte 1: expected 0, got {mem[off+1]}"
            )
            assert mem[off + 2] == y, (
                f"Pixel ({x},{y}) byte 2: expected {y}, got {mem[off+2]}"
            )
            assert mem[off + 3] == 0xFF, (
                f"Pixel ({x},{y}) byte 3: expected 255, got {mem[off+3]}"
            )


# ── Test 6: bitwise ops, shifts, xchg, push/pop ──


def test_bitstack():
    regs, flags, cycles = run_sim("prog_bitstack.bin")
    assert regs["ax"] == 0xFF00
    assert regs["bx"] == 0xFF01  # NEG 0x00FF
    assert regs["cx"] == 0xFF01  # pop ← pushed bx
    assert regs["dx"] == 0xFF00  # pop ← pushed ax
    assert regs["sp"] == 1000
    assert regs["si"] == 200  # xchg
    assert regs["di"] == 100
    assert cycles == 87, f"Expected 87 cycles, got {cycles}"


# ── Test 7: transfer penalty for word access at odd addresses ──


def test_transfer_penalty():
    regs, flags, cycles = run_sim("prog_penalty.bin")
    assert regs["ax"] == 0x68AC, f"ax: expected 0x68AC, got {regs.get('ax')}"
    assert regs["bx"] == 1001
    assert regs["si"] == 2000
    assert "PF" in flags
    assert cycles == 73, f"Expected 73 cycles, got {cycles}"


# ── Test 8: per-instruction cycle breakdown with transfer penalties ──


def test_penalty_cycle_breakdown():
    """Verify --cycles output shows correct EA and transfer penalty per instruction."""
    entries, total = run_sim_cycles("prog_penalty.bin")
    assert total == 73, f"TOTAL expected 73, got {total}"
    assert len(entries) == 6, f"Expected 6 instructions, got {len(entries)}"

    # Instruction at offset 3: mov word [bx], 0x1234  (bx=1001, odd address)
    # base=10 (MOV mem,imm), ea=5 ([BX]), penalty=4 (word at odd)
    off, base, ea, pen, tot = entries[1]
    assert off == 3, f"Expected offset 3, got {off}"
    assert base == 10, f"Base: expected 10, got {base}"
    assert ea == 5, f"EA: expected 5, got {ea}"
    assert pen == 4, f"Penalty: expected 4 (odd addr word write), got {pen}"
    assert tot == 19, f"Total: expected 19, got {tot}"

    # Instruction at offset 7: mov ax, [bx]  (bx=1001, odd address)
    # base=8 (MOV reg,mem), ea=5 ([BX]), penalty=4 (word at odd)
    off, base, ea, pen, tot = entries[2]
    assert off == 7, f"Expected offset 7, got {off}"
    assert base == 8
    assert ea == 5
    assert pen == 4, f"Penalty: expected 4, got {pen}"

    # Instruction at offset 12: mov word [si], 0x5678  (si=2000, even address)
    # base=10, ea=5, penalty=0 (even addr)
    off, base, ea, pen, tot = entries[4]
    assert off == 12, f"Expected offset 12, got {off}"
    assert base == 10
    assert ea == 5
    assert pen == 0, f"Penalty: expected 0 (even addr), got {pen}"
    assert tot == 15

    # Instruction at offset 16: add ax, [si]  (si=2000, even address)
    # base=9 (ADD reg,mem), ea=5, penalty=0
    off, base, ea, pen, tot = entries[5]
    assert off == 16, f"Expected offset 16, got {off}"
    assert base == 9
    assert ea == 5
    assert pen == 0


# ── Test 9: cross-validate instruction count against ndisasm ──


def test_ndisasm_crosscheck():
    """Verify simulator decodes same instruction count as ndisasm for straight-line code."""
    bin_path = os.path.join(BIN_DIR, "prog_regops.bin")

    # Run ndisasm
    r1 = subprocess.run(
        ["ndisasm", "-b", "16", bin_path], capture_output=True, text=True
    )
    assert r1.returncode == 0, f"ndisasm failed: {r1.stderr}"
    ndisasm_lines = [l for l in r1.stdout.strip().split("\n") if l.strip()]
    ndisasm_count = len(ndisasm_lines)

    # Run sim86 --cycles
    entries, total = run_sim_cycles("prog_regops.bin")
    sim_count = len(entries)

    assert sim_count == ndisasm_count, (
        f"Instruction count mismatch: ndisasm={ndisasm_count}, sim86={sim_count}. "
        f"Simulator must correctly decode all instructions in the binary."
    )
    assert total == 39


# ── Test 10: regops --cycles individual instruction timing ──


def test_regops_cycle_detail():
    """Verify per-instruction timing for straight-line register operations."""
    entries, total = run_sim_cycles("prog_regops.bin")
    assert total == 39
    assert len(entries) == 10

    # All MOV reg,imm should be base=4, ea=0, penalty=0
    for i in [0, 1, 2, 3, 6, 7, 8, 9]:
        _, base, ea, pen, tot = entries[i]
        assert base == 4, f"Instr {i}: base expected 4, got {base}"
        assert ea == 0
        assert pen == 0
        assert tot == 4

    # ADD reg,reg at index 4: base=3
    _, base, ea, pen, tot = entries[4]
    assert base == 3, f"ADD reg,reg: base expected 3, got {base}"
    assert tot == 3

    # SUB reg,imm at index 5: base=4
    _, base, ea, pen, tot = entries[5]
    assert base == 4, f"SUB reg,imm: base expected 4, got {base}"
    assert tot == 4
