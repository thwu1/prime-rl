
import subprocess
import re
import os
import pytest

SIM = "/app/sim8086"
PROG_DIR = "/app/programs"


def run_sim(binary, memdump=None):
    """Run the simulator on a binary and parse the output."""
    cmd = [SIM, os.path.join(PROG_DIR, binary)]
    if memdump:
        cmd.extend(["--memdump", hex(memdump[0]), str(memdump[1])])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (
        f"Simulator failed on {binary} (rc={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return parse_output(result.stdout)


def parse_output(output):
    """Parse simulator stdout into a dict of register values and memory."""
    state = {}
    for line in output.strip().split("\n"):
        line = line.strip()
        m = re.match(r"([A-Z]{2}): 0x([0-9A-Fa-f]{4})", line)
        if m:
            state[m.group(1).lower()] = int(m.group(2), 16)
            continue
        m = re.match(r"FLAGS: (.*)", line)
        if m:
            state["flags"] = m.group(1).strip()
            continue
        m = re.match(r"MEM\[0x([0-9A-Fa-f]+)\]: (.*)", line)
        if m:
            addr = int(m.group(1), 16)
            bytes_hex = m.group(2).strip().split()
            state[f"mem_{addr}"] = [int(b, 16) for b in bytes_hex]
    return state


# ---------------------------------------------------------------------------
# Test 1: Register moves and basic arithmetic
#   mov ax, 100; mov bx, 200; mov cx, ax; add ax, bx; sub bx, 50;
#   mov dx, ax; add dx, bx
# ---------------------------------------------------------------------------
class TestRegisterArithmetic:
    def test_ax(self):
        s = run_sim("test1")
        assert s["ax"] == 0x012C, f"AX expected 300 (0x012C), got 0x{s['ax']:04X}"

    def test_bx(self):
        s = run_sim("test1")
        assert s["bx"] == 0x0096, f"BX expected 150 (0x0096), got 0x{s['bx']:04X}"

    def test_cx(self):
        s = run_sim("test1")
        assert s["cx"] == 0x0064, f"CX expected 100 (0x0064), got 0x{s['cx']:04X}"

    def test_dx(self):
        s = run_sim("test1")
        assert s["dx"] == 0x01C2, f"DX expected 450 (0x01C2), got 0x{s['dx']:04X}"


# ---------------------------------------------------------------------------
# Test 2: Loop via conditional jump
#   mov cx, 5; mov ax, 0; loop: add ax, cx; sub cx, 1; jnz loop
#   Result: ax = 5+4+3+2+1 = 15, cx = 0
# ---------------------------------------------------------------------------
class TestLoop:
    def test_ax_sum(self):
        s = run_sim("test2")
        assert s["ax"] == 0x000F, f"AX expected 15, got {s['ax']}"

    def test_cx_zero(self):
        s = run_sim("test2")
        assert s["cx"] == 0x0000, f"CX expected 0, got {s['cx']}"

    def test_zero_flag(self):
        s = run_sim("test2")
        assert "Z" in s.get("flags", ""), "ZF should be set after loop ends"


# ---------------------------------------------------------------------------
# Test 3: Memory read/write
#   Store 42 and 58 at addresses 0x1000 and 0x1002, load back, add, store sum
# ---------------------------------------------------------------------------
class TestMemoryOps:
    def test_registers(self):
        s = run_sim("test3")
        assert s["ax"] == 0x0064, f"AX expected 100, got {s['ax']}"
        assert s["bx"] == 0x003A, f"BX expected 58, got {s['bx']}"

    def test_memory(self):
        s = run_sim("test3", memdump=(0x1000, 6))
        mem = s.get("mem_4096")
        assert mem is not None, "Memory dump at 0x1000 not found in output"
        expected = [0x2A, 0x00, 0x3A, 0x00, 0x64, 0x00]
        assert mem == expected, f"Memory mismatch: {mem} != {expected}"


# ---------------------------------------------------------------------------
# Test 4: Shift-accumulate loop with memory writes
#   4 iterations: ax *= 3 each iter via shl+add, stores doubled values
#   Final: ax=81, bx=54, cx=0, bp=0x2008
# ---------------------------------------------------------------------------
class TestShiftLoop:
    def test_registers(self):
        s = run_sim("test4")
        assert s["ax"] == 0x0051, f"AX expected 81 (0x0051), got 0x{s['ax']:04X}"
        assert s["bx"] == 0x0036, f"BX expected 54 (0x0036), got 0x{s['bx']:04X}"
        assert s["cx"] == 0x0000, f"CX expected 0, got {s['cx']}"
        assert s["bp"] == 0x2008, f"BP expected 0x2008, got 0x{s['bp']:04X}"

    def test_memory(self):
        s = run_sim("test4", memdump=(0x2000, 8))
        mem = s.get("mem_8192")
        assert mem is not None, "Memory dump at 0x2000 not found"
        expected = [0x02, 0x00, 0x06, 0x00, 0x12, 0x00, 0x36, 0x00]
        assert mem == expected, f"Memory mismatch: {mem} != {expected}"


# ---------------------------------------------------------------------------
# Test 5: Rectangle drawing — 64x64 pixel image in memory starting at byte 256
#   Each pixel: [cx_low, cx_high, dx_low, 0xFF] (x-coord, y-coord, alpha)
#   Final: bp=0x4100, dx=64, cx=64
# ---------------------------------------------------------------------------
class TestRectangle:
    def test_final_registers(self):
        s = run_sim("test5")
        assert s["bp"] == 0x4100, f"BP expected 0x4100, got 0x{s['bp']:04X}"
        assert s["dx"] == 0x0040, f"DX expected 64, got {s['dx']}"
        assert s["cx"] == 0x0040, f"CX expected 64, got {s['cx']}"

    def test_pixel_origin(self):
        """Pixel (0, 0) at address 256."""
        s = run_sim("test5", memdump=(256, 4))
        mem = s.get("mem_256")
        assert mem == [0x00, 0x00, 0x00, 0xFF], f"Pixel(0,0) mismatch: {mem}"

    def test_pixel_10_20(self):
        """Pixel (10, 20) at address 256 + (20*64+10)*4 = 5416."""
        offset = 256 + (20 * 64 + 10) * 4
        s = run_sim("test5", memdump=(offset, 4))
        mem = s.get(f"mem_{offset}")
        assert mem == [0x0A, 0x00, 0x14, 0xFF], f"Pixel(10,20) mismatch: {mem}"

    def test_pixel_63_63(self):
        """Pixel (63, 63) at address 256 + (63*64+63)*4 = 16636."""
        offset = 256 + (63 * 64 + 63) * 4
        s = run_sim("test5", memdump=(offset, 4))
        mem = s.get(f"mem_{offset}")
        assert mem == [0x3F, 0x00, 0x3F, 0xFF], f"Pixel(63,63) mismatch: {mem}"

    def test_pixel_mid_row(self):
        """Pixel (32, 0) at address 256 + 32*4 = 384."""
        offset = 256 + 32 * 4
        s = run_sim("test5", memdump=(offset, 4))
        mem = s.get(f"mem_{offset}")
        assert mem == [0x20, 0x00, 0x00, 0xFF], f"Pixel(32,0) mismatch: {mem}"


# ---------------------------------------------------------------------------
# Test 6: Bitwise operations (AND, OR, XOR, NOT, NEG)
#   Final: ax=0x1235, bx=0xFF00, cx=0x1235, dx=0xED35, si=0x0100
#   Memory: [0x100]=0x1235, [0x102]=0xFF00
# ---------------------------------------------------------------------------
class TestBitwise:
    def test_registers(self):
        s = run_sim("test6")
        assert s["ax"] == 0x1235, f"AX expected 0x1235, got 0x{s['ax']:04X}"
        assert s["bx"] == 0xFF00, f"BX expected 0xFF00, got 0x{s['bx']:04X}"
        assert s["cx"] == 0x1235, f"CX expected 0x1235, got 0x{s['cx']:04X}"
        assert s["dx"] == 0xED35, f"DX expected 0xED35, got 0x{s['dx']:04X}"
        assert s["si"] == 0x0100, f"SI expected 0x0100, got 0x{s['si']:04X}"

    def test_memory(self):
        s = run_sim("test6", memdump=(0x100, 4))
        mem = s.get("mem_256")
        assert mem is not None, "Memory dump at 0x100 not found"
        expected = [0x35, 0x12, 0x00, 0xFF]
        assert mem == expected, f"Memory mismatch: {mem} != {expected}"

    def test_sign_flag(self):
        s = run_sim("test6")
        flags = s.get("flags", "")
        assert "S" in flags, "SF should be set (last XOR result has bit 15 set)"

    def test_no_carry_flag(self):
        s = run_sim("test6")
        flags = s.get("flags", "")
        assert "C" not in flags, "CF should be clear after XOR"

    def test_no_zero_flag(self):
        s = run_sim("test6")
        flags = s.get("flags", "")
        assert "Z" not in flags, "ZF should be clear (result is nonzero)"
