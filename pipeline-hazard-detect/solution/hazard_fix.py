#!/usr/bin/env python3
"""
Implement pipeline data hazard detection for MaxiCore32.

This script modifies /app/src/maxicore32.v to add automatic detection of:
  1. Register RAW (read-after-write) data hazards
  2. Status-flag hazards (ALU -> conditional branch/jump)

The fix adds combinational logic that compares the destination register of the
instruction leaving stage 1 (about to enter stage 2) with the source registers
of the instruction about to enter stage 1.  When a conflict is found the
existing `insert_nops` stall signal is asserted, which inserts a pipeline
bubble and holds the program counter.
"""


import sys

MAXICORE_PATH = "/app/src/maxicore32.v"

# ── The hazard-detection logic to splice in ──────────────────────────
HAZARD_LOGIC = r"""
    // ================================================================
    // Pipeline hazard detection unit
    // ================================================================

    // Raw instruction word being fetched from memory (before NOP gating)
    wire [4:0] fetch_opcode   = cpu_data_in[31:27];
    wire [3:0] fetch_reg_data = cpu_data_in[23:20];   // reg1: data / dest
    wire [3:0] fetch_reg_addr = cpu_data_in[19:16];   // reg2: address / operand
    wire [3:0] fetch_reg_oper = cpu_data_in[11:8];    // reg3: second operand

    // Instruction that just left stage 1 and is about to enter stage 2
    wire [4:0] stage2_opcode = memorystage1_outbound_instruction[31:27];
    wire [3:0] stage2_dest   = memorystage1_outbound_instruction[23:20];

    // Does the stage-2 instruction write a general-purpose register?
    wire stage2_writes_reg = (stage2_opcode == OPCODE_LOADI) |
                             (stage2_opcode == OPCODE_LOAD)  |
                             (stage2_opcode == OPCODE_LOADR) |
                             (stage2_opcode == OPCODE_ALUM)  |
                             (stage2_opcode == OPCODE_ALUMI) |
                             (stage2_opcode == OPCODE_ALU);

    // Which register-file read ports does the fetched instruction use?
    wire fetch_uses_reg2 = (fetch_opcode == OPCODE_LOAD)   |
                           (fetch_opcode == OPCODE_STORE)  |
                           (fetch_opcode == OPCODE_LOADR)  |
                           (fetch_opcode == OPCODE_STORER) |
                           (fetch_opcode == OPCODE_ALUM)   |
                           (fetch_opcode == OPCODE_ALUMI)  |
                           (fetch_opcode == OPCODE_ALU)    |
                           (fetch_opcode == OPCODE_JUMP);

    wire fetch_uses_reg3 = (fetch_opcode == OPCODE_ALUM)   |
                           (fetch_opcode == OPCODE_LOADR)  |
                           (fetch_opcode == OPCODE_STORER);

    // Stores read reg1 (bits 23:20) as the data source
    wire fetch_uses_reg1 = (fetch_opcode == OPCODE_STORE)  |
                           (fetch_opcode == OPCODE_STORER);

    // Only check when the pipeline is not already stalled for another reason
    wire not_already_stalling = ~memorystage1_memory_access_cycle
                              & ~memorystage1_control_flow_start_cycle
                              & ~last_control_flow_start_cycle
                              & ~memorystage1_halting;

    // Register RAW data hazard
    wire data_hazard = not_already_stalling & stage2_writes_reg & (
        (fetch_uses_reg2 & (fetch_reg_addr == stage2_dest)) |
        (fetch_uses_reg3 & (fetch_reg_oper == stage2_dest)) |
        (fetch_uses_reg1 & (fetch_reg_data == stage2_dest))
    );

    // Status-flag hazard: ALU in stage 2 updates flags while a conditional
    // branch/jump in the fetch position needs to read them.
    wire stage2_writes_status = (stage2_opcode == OPCODE_ALUM)  |
                                (stage2_opcode == OPCODE_ALUMI) |
                                (stage2_opcode == OPCODE_ALU);

    wire [3:0] fetch_condition = cpu_data_in[15:12];
    wire fetch_reads_status = ((fetch_opcode == OPCODE_BRANCH) |
                               (fetch_opcode == OPCODE_JUMP))
                            & (fetch_condition != COND_AL);

    wire status_hazard = not_already_stalling
                       & stage2_writes_status
                       & fetch_reads_status;

"""

# ── Original and replacement insert_nops lines ──────────────────────
OLD_INSERT_NOPS = (
    "    wire insert_nops = memorystage1_memory_access_cycle | "
    "memorystage1_control_flow_start_cycle |\n"
    "        last_control_flow_start_cycle | memorystage1_halting;"
)

NEW_INSERT_NOPS = (
    "    wire insert_nops = memorystage1_memory_access_cycle | "
    "memorystage1_control_flow_start_cycle |\n"
    "        last_control_flow_start_cycle | memorystage1_halting | "
    "data_hazard | status_hazard;"
)


def main():
    with open(MAXICORE_PATH, "r") as f:
        src = f.read()

    if OLD_INSERT_NOPS not in src:
        print("ERROR: could not locate the insert_nops wire in maxicore32.v",
              file=sys.stderr)
        sys.exit(1)

    # Splice hazard logic just before insert_nops
    patched = src.replace(
        OLD_INSERT_NOPS,
        HAZARD_LOGIC + NEW_INSERT_NOPS,
    )

    with open(MAXICORE_PATH, "w") as f:
        f.write(patched)

    print("Hazard detection logic added to maxicore32.v")


if __name__ == "__main__":
    main()
