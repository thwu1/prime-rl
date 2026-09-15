
import subprocess
import re
import pytest


def run_simulation():
    """Compile and run the MaxiCore32 Verilog simulation."""
    # Compile
    compile_result = subprocess.run(
        [
            "iverilog",
            "-g2012",
            "-I/app/src",
            "-I/app/tb",
            "-o",
            "/tmp/maxicore32_tb.vvp",
            "/app/src/maxicore32.v",
            "/app/src/memorystage1.v",
            "/app/src/registersstage2.v",
            "/app/src/registers.v",
            "/app/src/alu.v",
            "/app/src/agu.v",
            "/app/src/businterface.v",
            "/app/tb/maxicore32_tb.v",
            "/app/tb/memory.v",
            "/app/tb/led.v",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if compile_result.returncode != 0:
        raise RuntimeError(
            f"Verilog compilation failed:\n{compile_result.stderr}\n{compile_result.stdout}"
        )

    # Simulate
    sim_result = subprocess.run(
        ["vvp", "/tmp/maxicore32_tb.vvp"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    output = sim_result.stdout + "\n" + sim_result.stderr
    return output


def parse_registers(output):
    """Parse register values from the simulation output after HALT."""
    # Find the register dump section
    reg_section_match = re.search(
        r"=== REGISTERS ===(.*?)=== END REGISTERS ===", output, re.DOTALL
    )
    if not reg_section_match:
        # Try without END marker
        reg_section_match = re.search(r"=== REGISTERS ===(.*?)$", output, re.DOTALL)
    if not reg_section_match:
        raise RuntimeError("Could not find register dump in simulation output")

    reg_section = reg_section_match.group(1)

    registers = {}
    for match in re.finditer(r"r(\d+)\s*=\s*([0-9a-fA-F]{8})", reg_section):
        reg_num = int(match.group(1))
        reg_val = int(match.group(2), 16)
        registers[reg_num] = reg_val

    return registers


# Expected register values with correct operand forwarding
EXPECTED_REGISTERS = {
    1: 0x0000002A,  # 42:  loadi.u r1, 42
    2: 0x00000054,  # 84:  add r2, r1, r1      (forward r1 from LOADI.u)
    3: 0x0000007E,  # 126: add r3, r2, r1      (forward r2 from ALU)
    4: 0x00000054,  # 84:  sub r4, r3, r1      (forward r3 from ALU)
    5: 0x000000C8,  # 200: loadi.u r5, 200
    6: 0x000000FA,  # 250: add r6, r5, 50      (forward r5 from LOADI.u)
    7: 0x000000A6,  # 166: sub r7, r6, r4      (forward r6 from ALUMI)
    8: 0xFFFFFFF1,  # -15: loadi.s r8, -15
    9: 0x000000B9,  # 185: add r9, r8, r5      (forward r8 from LOADI.s)
    10: 0x00000007,  # 7:  loadi.u r10, 7
    11: 0x00000031,  # 49: mulu r11, r10, r10   (forward r10 to both)
    12: 0xFFFFFFCE,  # ~49: not r12, r11        (forward r11 from ALU)
}


@pytest.fixture(scope="module")
def simulation_output():
    """Run the simulation once and cache the output."""
    return run_simulation()


@pytest.fixture(scope="module")
def registers(simulation_output):
    """Parse registers from simulation output."""
    return parse_registers(simulation_output)


def test_simulation_halts(simulation_output):
    """Verify the simulation halted successfully."""
    assert "HALTED" in simulation_output, (
        "Simulation did not halt - possible infinite loop or crash"
    )


def test_no_bus_error(simulation_output):
    """Verify no bus errors occurred during simulation."""
    assert "BUS ERROR" not in simulation_output, (
        "Bus error occurred during simulation"
    )


@pytest.mark.parametrize(
    "reg_num,expected_val",
    list(EXPECTED_REGISTERS.items()),
    ids=[f"r{k}" for k in EXPECTED_REGISTERS],
)
def test_register_value(registers, reg_num, expected_val):
    """Verify each register has the correct value after forwarding."""
    assert reg_num in registers, f"Register r{reg_num} not found in simulation output"
    actual = registers[reg_num]
    assert actual == expected_val, (
        f"r{reg_num}: expected 0x{expected_val:08X} ({expected_val}), "
        f"got 0x{actual:08X} ({actual}). "
        f"This indicates a forwarding bug for this instruction."
    )
