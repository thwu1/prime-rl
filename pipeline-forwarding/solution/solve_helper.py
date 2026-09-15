#!/usr/bin/env python3
"""
Implement operand forwarding in the MaxiCore32 processor.

This script modifies /app/src/maxicore32.v to add data hazard detection
and forwarding bypass logic between the writeback stage (registersstage2)
and the decode/read stage (memorystage1).
"""

MAXICORE32_PATH = "/app/src/maxicore32.v"

# Read the original file
with open(MAXICORE32_PATH, "r") as f:
    content = f.read()

# 1. Add forwarding logic block after the AGU instantiation
#    and before the ALU instantiation

forwarding_block = """
    // === Operand Forwarding Logic ===
    // Detect when the writeback stage (registersstage2) is writing a register
    // that the decode stage (memorystage1) is simultaneously reading.
    // In this 2-stage pipeline, the register file write from stage2 takes effect
    // one cycle after the write signals are set (non-blocking assignment).
    // Forwarding bypasses the register file to provide the correct value immediately.

    wire fwd_write = register_file_write;
    wire fwd_write_imm = register_file_write_immediate;
    wire fwd_active = fwd_write | fwd_write_imm;

    // Compute the value that will be written to the register file
    // For write_immediate, reconstruct the full 32-bit value from the immediate and type
    reg [31:0] fwd_imm_value;
    always @(*) begin
        case (register_file_write_immediate_type)
            IT_UNSIGNED: fwd_imm_value = {16'h0, register_file_write_immediate_data};
            IT_SIGNED:   fwd_imm_value = {{16{register_file_write_immediate_data[15]}},
                                          register_file_write_immediate_data};
            IT_TOP:      fwd_imm_value = {register_file_write_immediate_data,
                                          register_file_read_reg2_data[15:0]};
            IT_BOTTOM:   fwd_imm_value = {register_file_read_reg2_data[31:16],
                                          register_file_write_immediate_data};
            default:     fwd_imm_value = 32'h0;
        endcase
    end

    // Select between ALU/memory write data and immediate write data
    wire [31:0] fwd_value = fwd_write ? register_file_write_data : fwd_imm_value;

    // Detect forwarding matches on each register read port
    wire fwd_match_reg1 = fwd_active &&
        (register_file_write_index == register_file_read_reg1_index);
    wire fwd_match_reg2 = fwd_active &&
        (register_file_write_index == register_file_read_reg2_index);
    wire fwd_match_reg3 = fwd_active &&
        (register_file_write_index == register_file_read_reg3_index);

    // Effective register values: forwarded when hazard detected, otherwise from register file
    wire [31:0] eff_reg1_data = fwd_match_reg1 ? fwd_value : register_file_read_reg1_data;
    wire [31:0] eff_reg2_data = fwd_match_reg2 ? fwd_value : register_file_read_reg2_data;
    wire [31:0] eff_reg3_data = fwd_match_reg3 ? fwd_value : register_file_read_reg3_data;

"""

# Insert forwarding block before the ALU instantiation
content = content.replace(
    "    wire [4:0] alu_op;",
    forwarding_block + "    wire [4:0] alu_op;",
)

# 2. Update AGU to use forwarded register values
content = content.replace(
    "        .base_address(register_file_read_reg2_data),",
    "        .base_address(eff_reg2_data),",
)
content = content.replace(
    "        .register_data(register_file_read_reg3_data),",
    "        .register_data(eff_reg3_data),",
)

# 3. Update ALU reg2 input to use forwarded value
content = content.replace(
    """    assign alu_reg2 = memorystage1_branch_cycle == 1'b0 ?
        register_file_read_reg2_data :
        program_counter_read_data;""",
    """    assign alu_reg2 = memorystage1_branch_cycle == 1'b0 ?
        eff_reg2_data :
        program_counter_read_data;""",
)

# 4. Update ALU reg3 input to use forwarded value
content = content.replace(
    """    assign alu_reg3 = memorystage1_alu_immediate_cycle == 1'b0 ?
        register_file_read_reg3_data :
        {{ 16 { memorystage1_immediate[15] }}, memorystage1_immediate };""",
    """    assign alu_reg3 = memorystage1_alu_immediate_cycle == 1'b0 ?
        eff_reg3_data :
        {{ 16 { memorystage1_immediate[15] }}, memorystage1_immediate };""",
)

# 5. Update store data output to use forwarded value
content = content.replace(
    """    assign cpu_data_out = memorystage1_memory_access_cycle == 1'b0 ?
        32'h0 :
        register_file_read_reg1_data;""",
    """    assign cpu_data_out = memorystage1_memory_access_cycle == 1'b0 ?
        32'h0 :
        eff_reg1_data;""",
)

# Write the modified file
with open(MAXICORE32_PATH, "w") as f:
    f.write(content)

print("Operand forwarding implemented in maxicore32.v")
