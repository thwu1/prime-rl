#!/usr/bin/env python3
"""
Implement pipeline hazard detection and automatic stalling for MaxiCore32.

The MaxiCore32 is a 2-stage pipelined processor that currently requires manual
NOP insertion after register-writing instructions (LOADI, ALU) to avoid
Read-After-Write (RAW) data hazards.

This script modifies maxicore32.v to add a combinational hazard detection unit
that compares the destination register of the instruction leaving stage 1
(outbound_instruction) with the source registers of the instruction about to
enter stage 1 (cpu_data_in). When a match is found, a pipeline bubble (NOP) is
automatically inserted and the PC is frozen, giving the register file time to
complete the write before the dependent instruction reads it.
"""

import os

MAXICORE32_PATH = "/app/src/maxicore32.v"

# Read the original file
with open(MAXICORE32_PATH, "r") as f:
    content = f.read()

# The key modification: replace the insert_nops logic with hazard-aware version.
#
# Original:
#   wire insert_nops = memorystage1_memory_access_cycle | memorystage1_control_flow_start_cycle |
#       last_control_flow_start_cycle | memorystage1_halting;
#
# We add hazard detection that checks:
# 1. Does the instruction just decoded (outbound_instruction) write to a register?
# 2. Does the next instruction (cpu_data_in) read from that same register?
# If both are true and no other NOP condition is active, insert a stall.

old_insert_nops = """    wire insert_nops = memorystage1_memory_access_cycle | memorystage1_control_flow_start_cycle |
        last_control_flow_start_cycle | memorystage1_halting;"""

new_hazard_logic = """    // === Hazard Detection Unit ===
    // Detect RAW (Read-After-Write) data hazards between consecutive instructions.
    // The instruction that just finished stage 1 (in outbound_instruction) may write
    // to a register. If the next instruction (from cpu_data_in) reads that register,
    // we must stall the pipeline for one cycle to let the write complete.

    wire [4:0] hd_prev_opcode = memorystage1_outbound_instruction[31:27];
    wire [3:0] hd_prev_dest = memorystage1_outbound_instruction[23:20];

    // Which opcodes write to a register via the normal write path or write_immediate?
    wire hd_prev_writes = (hd_prev_opcode == OPCODE_LOADI) |
                           (hd_prev_opcode == OPCODE_ALUM) |
                           (hd_prev_opcode == OPCODE_ALUMI) |
                           (hd_prev_opcode == OPCODE_ALU);

    // Extract the incoming instruction's fields (before NOP substitution)
    wire [4:0] hd_curr_opcode = cpu_data_in[31:27];

    // Which opcodes read from reg_address_index (bits 19:16)?
    wire hd_curr_reads_addr = (hd_curr_opcode == OPCODE_ALUM) |
                               (hd_curr_opcode == OPCODE_ALUMI) |
                               (hd_curr_opcode == OPCODE_ALU) |
                               (hd_curr_opcode == OPCODE_LOAD) |
                               (hd_curr_opcode == OPCODE_LOADR) |
                               (hd_curr_opcode == OPCODE_STORE) |
                               (hd_curr_opcode == OPCODE_STORER) |
                               (hd_curr_opcode == OPCODE_JUMP);

    // Which opcodes read from reg_operand_index (bits 11:8)?
    wire hd_curr_reads_oper = (hd_curr_opcode == OPCODE_ALUM) |
                               (hd_curr_opcode == OPCODE_LOADR) |
                               (hd_curr_opcode == OPCODE_STORER);

    // Which opcodes read from reg_data_index (bits 23:20) as a source?
    // STORE/STORER read reg_data_index as the data to be stored.
    wire hd_curr_reads_data = (hd_curr_opcode == OPCODE_STORE) |
                               (hd_curr_opcode == OPCODE_STORER);

    // Other NOP-insertion conditions (memory access, control flow, halt)
    wire hd_other_nops = memorystage1_memory_access_cycle |
        memorystage1_control_flow_start_cycle |
        last_control_flow_start_cycle | memorystage1_halting;

    // Only check for data hazards when we are actually fetching an instruction
    // (not when other NOP conditions are active, as cpu_data_in may not be valid)
    wire data_hazard = ~hd_other_nops & hd_prev_writes & (
        (hd_curr_reads_addr & (hd_prev_dest == cpu_data_in[19:16])) |
        (hd_curr_reads_oper & (hd_prev_dest == cpu_data_in[11:8])) |
        (hd_curr_reads_data & (hd_prev_dest == cpu_data_in[23:20]))
    );

    wire insert_nops = hd_other_nops | data_hazard;"""

if old_insert_nops not in content:
    print("ERROR: Could not find the insert_nops line to replace")
    exit(1)

content = content.replace(old_insert_nops, new_hazard_logic)

with open(MAXICORE32_PATH, "w") as f:
    f.write(content)

print("Successfully added hazard detection to maxicore32.v")
