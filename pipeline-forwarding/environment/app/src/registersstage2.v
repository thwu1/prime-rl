`include "registers.vh"
`include "businterface.vh"
`include "opcodes.vh"
`include "alu.vh"

module registersstage2
    (
        input       reset,
        input       clock,

        input       [31:0] return_address,
        input       [31:0] inbound_instruction,
        input       [31:0] data_in,
        output reg  [3:0] write_index,
        output reg  write,
        output reg  [31:0] write_data,
        output reg  write_immediate,
        output reg  [15:0] write_immediate_data,
        output reg  [1:0] write_immediate_type,
        output reg  alu_cycle,
        output reg  jump,
        output reg  status_register_write,
        input       alu_carry, alu_zero, alu_neg, alu_over
    );

    wire [4:0] opcode = inbound_instruction[31:27];
    wire [3:0] alu_condition = inbound_instruction[15:12];
    reg cond_true;

    always @ (*) begin
        case (alu_condition)
            COND_AL:
                cond_true = 1'b1;
            COND_EQ:
                cond_true = alu_zero;
            COND_NE:
                cond_true = ~alu_zero;
            COND_CS:
                cond_true = alu_carry;
            COND_CC:
                cond_true = ~alu_carry;
            COND_MI:
                cond_true = alu_neg;
            COND_PL:
                cond_true = ~alu_neg;
            COND_VS:
                cond_true = alu_over;
            COND_VC:
                cond_true = ~alu_over;
            COND_HI:
                cond_true = ~alu_carry & ~alu_zero;
            COND_LS:
                cond_true = alu_carry | alu_zero;
            COND_GE:
                cond_true = ~(alu_neg ^ alu_over);
            COND_LT:
                cond_true = alu_neg ^ alu_over;
            COND_GT:
                cond_true = ~alu_zero & ~(alu_neg ^ alu_over);
            COND_LE:
                cond_true = alu_zero | (alu_neg ^ alu_over);
            default:
                cond_true = 1'b0;
        endcase
    end

    always @ (posedge clock) begin
        if (reset) begin
            write_index <= 4'h0;
            write_immediate_type <= IT_UNSIGNED;
            write_immediate_data <= 16'h0;
            write_immediate <= 1'b0;
            write <= 1'b0;
            alu_cycle <= 1'b0;
            jump <= 1'b0;
            status_register_write <= 1'b0;
        end else begin
            write_immediate <= 1'b0;
            write <= 1'b0;
            alu_cycle <= 1'b0;
            jump <= 1'b0;
            status_register_write <= 1'b0;

            case (opcode)
                OPCODE_LOADI: begin
                    $display("STAGE2: OPCODE_LOADI");
                    write_immediate_type <= inbound_instruction[26:25];
                    write_immediate_data <= inbound_instruction[15:0];
                    write_immediate <= 1'b1;
                end
                OPCODE_LOAD,
                OPCODE_LOADR: begin
                    $display("STAGE2: OPCODE_LOAD[R]");
                    write <= 1'b1;
                    case (inbound_instruction[26:25])
                        CW_BYTE: begin
                            if (inbound_instruction[24]) begin
                                write_data <= {{ 24 { data_in[7] }}, data_in[7:0] };
                            end else begin
                                write_data <= { 24'h0, data_in[7:0] };
                            end
                        end
                        CW_WORD: begin
                            if (inbound_instruction[24]) begin
                                write_data <= {{ 16 { data_in[15] }}, data_in[15:0] };
                            end else begin
                                write_data <= { 16'h0, data_in[15:0] };
                            end
                        end
                        default: begin
                            write_data <= data_in;
                        end
                    endcase
                end
                OPCODE_ALUM: begin
                    $display("STAGE2: OPCODE_ALUM");
                end
                OPCODE_ALUMI: begin
                    $display("STAGE2: OPCODE_ALUMI");
                end
                OPCODE_ALU: begin
                    $display("STAGE2: OPCODE_ALU");
                end
                OPCODE_BRANCH: begin
                    if (cond_true) begin
                        $display("STAGE2: OPCODE_BRANCH taken");
                        jump <= 1'b1;
                        if (inbound_instruction[24]) begin
                            write_data <= return_address;
                            write <= 1'b1;
                        end
                    end else begin
                        $display("STAGE2: OPCODE_BRANCH not taken");
                    end
                end
                OPCODE_JUMP: begin
                    if (cond_true) begin
                        $display("STAGE2: OPCODE_JUMP taken");
                        jump <= 1'b1;
                        if (inbound_instruction[24]) begin
                            write_data <= return_address;
                            write <= 1'b1;
                        end
                    end else begin
                        $display("STAGE2: OPCODE_JUMP not taken");
                    end
                end
                default: begin
                end
            endcase

            case (opcode)
                OPCODE_ALUM,
                OPCODE_ALUMI,
                OPCODE_ALU: begin
                    alu_cycle <= 1'b1;
                    status_register_write <= 1'b1;
                    write <= 1'b1;
                end
                default: begin
                end
            endcase

            write_index <= inbound_instruction[23:20];
        end
    end
endmodule
