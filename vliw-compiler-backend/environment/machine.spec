# VLIW Processor Specification
# Reference document for the optimizer implementation.
# All constraints below must be satisfied by generated bundles.

ARCH vliw3-scalar
WORD 32
REGISTERS 24
ZERO_REG r0
MEMORY 4096

# Execution slots — 3 per VLIW bundle, issued in parallel each cycle
SLOT A
  ADD SUB AND OR XOR SHL SHR MOV MOVI

SLOT B
  ADD SUB AND OR XOR SHL SHR MOV MOVI MUL

SLOT M
  LOAD STORE

# Instruction latencies: cycles from issue until result is readable
# A result issued at cycle C with latency L is available at cycle C+L
LATENCY ADD  1
LATENCY SUB  1
LATENCY AND  1
LATENCY OR   1
LATENCY XOR  1
LATENCY SHL  1
LATENCY SHR  1
LATENCY MOV  1
LATENCY MOVI 1
LATENCY MUL  2
LATENCY LOAD 3
LATENCY STORE 1

# Hazard model (both enforced at runtime by the simulator)
# RAW: reading a register with an unresolved pending write
# WAW: writing the same register from multiple slots in one bundle
HAZARD RAW strict
HAZARD WAW strict

# Instruction formats:
#   ALU:   OP rd rs1 rs2        (rd = rs1 OP rs2, 32-bit unsigned)
#   MOV:   MOV rd rs            (rd = rs)
#   MOVI:  MOVI rd imm          (rd = 32-bit unsigned immediate)
#   LOAD:  LOAD rd rs_addr      (rd = mem[regs[rs_addr]])
#   STORE: STORE rs_addr rs_val (mem[regs[rs_addr]] = regs[rs_val])
#   NOP:   NOP                  (empty slot)
