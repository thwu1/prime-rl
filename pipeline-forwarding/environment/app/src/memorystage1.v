`include "registers.vh"
`include "opcodes.vh"
`include "businterface.vh"
`include "alu.vh"

module memorystage1
    (
        input       reset,
        input       clock,

        input       [31:0] inbound_instruction,
        output reg  [31:0] outbound_instruction,
        output reg  memory_access_cycle,
        output reg  control_flow_start_cycle,
        output reg  memory_read,
        output reg  memory_write,
        output reg  [1:0] memory_cycle_width,
        output reg  [3:0] reg_address_index,
        output reg  [3:0] reg_data_index,
        output reg  [3:0] reg_operand_index,
        output reg  agu_immediate_mode,
        output reg  [15:0] immediate,
        output reg  [4:0] alu_op,
        output reg  alu_immediate_cycle,
        output reg  branch_cycle,
        output reg  halting
    );

    wire [4:0] opcode = inbound_instruction[31:27];

    always @ (posedge clock) begin
        if (reset) begin
            outbound_instruction <= { OPCODE_NOP, 27'h0 };
            memory_access_cycle <= 1'b0;
            control_flow_start_cycle <= 1'b0;
            alu_immediate_cycle <= 1'b0;
            branch_cycle <= 1'b0;
            halting <= 1'b0;
        end else begin
            memory_access_cycle <= 1'b0;
            control_flow_start_cycle <= 1'b0;
            memory_read <= 1'b0;
            memory_write <= 1'b0;
            alu_immediate_cycle <= 1'b0;
            branch_cycle <= 1'b0;

            $display("STAGE1: Got instruction %08x", inbound_instruction);

            case (opcode)
                OPCODE_NOP: begin
                    $display("STAGE1: NOP");
                end
                OPCODE_HALT: begin
                    $display("STAGE1: HALT");
                    halting <= 1'b1;
                end
                OPCODE_LOAD: begin
                    $display("STAGE1: OPCODE_LOAD");
                    memory_read <= 1'b1;
                    memory_write <= 1'b0;
                    memory_access_cycle <= 1'b1;
                    agu_immediate_mode <= 1'b1;
                    immediate <= inbound_instruction[15:0];
                end
                OPCODE_STORE: begin
                    $display("STAGE1: OPCODE_STORE");
                    memory_read <= 1'b0;
                    memory_write <= 1'b1;
                    memory_access_cycle <= 1'b1;
                    agu_immediate_mode <= 1'b1;
                    immediate <= inbound_instruction[15:0];
                end
                OPCODE_LOADR: begin
                    $display("STAGE1: OPCODE_LOADR");
                    memory_read <= 1'b1;
                    memory_write <= 1'b0;
                    memory_access_cycle <= 1'b1;
                    agu_immediate_mode <= 1'b0;
                end
                OPCODE_STORER: begin
                    $display("STAGE1: OPCODE_STORER");
                    memory_read <= 1'b0;
                    memory_write <= 1'b1;
                    memory_access_cycle <= 1'b1;
                    agu_immediate_mode <= 1'b0;
                end
                OPCODE_ALUM: begin
                    $display("STAGE1: OPCODE_ALUM");
                    alu_op <= { 1'b0, inbound_instruction[15:12] };
                    alu_immediate_cycle <= 1'b0;
                end
                OPCODE_ALUMI: begin
                    $display("STAGE1: OPCODE_ALUMI");
                    alu_op <= { 1'b0, inbound_instruction[15:12] };
                    immediate <= { inbound_instruction[26],
                        inbound_instruction[26:24], inbound_instruction[11:0] };
                    alu_immediate_cycle <= 1'b1;
                end
                OPCODE_ALU: begin
                    $display("STAGE1: OPCODE_ALU");
                    alu_op <= { 1'b1, inbound_instruction[15:12] };
                    alu_immediate_cycle <= 1'b0;
                end
                OPCODE_BRANCH: begin
                    $display("STAGE1: OPCODE_BRANCH");
                    alu_op <= { OP_ADD };
                    immediate <= {
                        inbound_instruction[19:16], inbound_instruction[11:0] };
                    alu_immediate_cycle <= 1'b1;
                    branch_cycle <= 1'b1;
                    control_flow_start_cycle <= 1'b1;
                end
                OPCODE_JUMP: begin
                    $display("STAGE1: OPCODE_JUMP");
                    alu_op <= { OP_COPY };
                    control_flow_start_cycle <= 1'b1;
                end
                default: begin
                end
            endcase

            memory_cycle_width <= inbound_instruction[26:25];

            reg_data_index <= inbound_instruction[23:20];
            reg_address_index <= inbound_instruction[19:16];
            reg_operand_index <= inbound_instruction[11:8];

            outbound_instruction <= inbound_instruction;
        end
    end
endmodule
