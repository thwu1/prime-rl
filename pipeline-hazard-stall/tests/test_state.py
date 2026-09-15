
import subprocess
import os
import re
import shutil

APP_DIR = "/app"
SRC_DIR = os.path.join(APP_DIR, "src")
TB_DIR = os.path.join(APP_DIR, "tb")
PROG_DIR = os.path.join(APP_DIR, "programs")

CORE_SRCS = [
    "maxicore32.v", "memorystage1.v", "registersstage2.v",
    "alu.v", "agu.v", "registers.v", "businterface.v",
    "memory.v", "led.v"
]


def run_simulation(program_hex):
    """Compile and run the MaxiCore32 simulation with the given hex program."""
    hex_src = os.path.join(PROG_DIR, program_hex)
    hex_dst = os.path.join(APP_DIR, "program.hex")
    shutil.copy(hex_src, hex_dst)

    src_files = [os.path.join(SRC_DIR, f) for f in CORE_SRCS]
    tb_file = os.path.join(TB_DIR, "maxicore32_tb.v")
    sim_out = os.path.join(APP_DIR, "sim_out")

    compile_cmd = ["iverilog", "-g2005-sv", "-I", SRC_DIR, "-o", sim_out] + src_files + [tb_file]
    result = subprocess.run(compile_cmd, capture_output=True, text=True, cwd=APP_DIR, timeout=60)
    assert result.returncode == 0, f"iverilog compilation failed:\n{result.stderr}"

    sim_cmd = ["vvp", sim_out]
    result = subprocess.run(sim_cmd, capture_output=True, text=True, cwd=APP_DIR, timeout=60)

    return result.stdout, result.stderr, result.returncode


def parse_registers(output):
    """Parse register values from simulation output."""
    registers = {}
    for match in re.finditer(r"REG r(\d+) = ([0-9a-fA-F]+)", output):
        reg_num = int(match.group(1))
        reg_val = int(match.group(2), 16)
        registers[reg_num] = reg_val
    return registers


def check_status(output):
    """Check simulation termination status."""
    if "STATUS: HALTED" in output:
        return "HALTED"
    elif "STATUS: BUS_ERROR" in output:
        return "BUS_ERROR"
    elif "STATUS: TIMEOUT" in output:
        return "TIMEOUT"
    return "UNKNOWN"


class TestNopRegression:
    """Regression: programs with manual NOPs must still produce correct results."""

    def test_nop_test(self):
        stdout, stderr, rc = run_simulation("nop_test.hex")
        status = check_status(stdout)
        assert status == "HALTED", (
            f"Expected HALTED, got {status}.\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )
        regs = parse_registers(stdout)
        assert regs[1] == 5, f"r1 expected 5, got {regs.get(1)}"
        assert regs[2] == 10, f"r2 expected 10, got {regs.get(2)}"
        assert regs[3] == 15, f"r3 expected 15, got {regs.get(3)}"
        assert regs[4] == 25, f"r4 expected 25, got {regs.get(4)}"


class TestHazardDetection:
    """Programs without manual NOPs must produce correct results after hazard
    detection is implemented."""

    def test_hazard_chain(self):
        """Chain of dependent ALU operations: loadi -> add -> add -> add, no NOPs."""
        stdout, stderr, rc = run_simulation("hazard_chain_test.hex")
        status = check_status(stdout)
        assert status == "HALTED", (
            f"Expected HALTED, got {status}.\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )
        regs = parse_registers(stdout)
        assert regs[1] == 5, f"r1 expected 5, got {regs.get(1)}"
        assert regs[2] == 10, f"r2 expected 10, got {regs.get(2)}"
        assert regs[3] == 15, f"r3 expected 15, got {regs.get(3)}"
        assert regs[4] == 25, f"r4 expected 25, got {regs.get(4)}"

    def test_mixed_hazards(self):
        """Mix of LOADI->ALU, ALU->ALU, ALU->ALUMI hazards and non-hazard gaps."""
        stdout, stderr, rc = run_simulation("mixed_hazard_test.hex")
        status = check_status(stdout)
        assert status == "HALTED", (
            f"Expected HALTED, got {status}.\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )
        regs = parse_registers(stdout)
        assert regs[1] == 7, f"r1 expected 7, got {regs.get(1)}"
        assert regs[2] == 3, f"r2 expected 3, got {regs.get(2)}"
        assert regs[3] == 10, f"r3 expected 10, got {regs.get(3)}"
        assert regs[4] == 1, f"r4 expected 1, got {regs.get(4)}"
        assert regs[5] == 9, f"r5 expected 9, got {regs.get(5)}"
        assert regs[6] == 16, f"r6 expected 16, got {regs.get(6)}"
        assert regs[7] == 18, f"r7 expected 18, got {regs.get(7)}"
