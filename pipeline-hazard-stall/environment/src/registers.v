`include "registers.vh"

module register_file
    (
        input   clock,

        input   [3:0] write_index,
        input   write,
        input   [31:0] write_data,
        input   write_immediate,
        input   [15:0] write_immediate_data,
        input   [1:0] write_immediate_type,
        input   [3:0] read_reg1_index, read_reg2_index, read_reg3_index,
        output  [31:0] read_reg1_data, read_reg2_data, read_reg3_data
    );

    reg [31:0] register_file [16];

    assign read_reg1_data = register_file[read_reg1_index];
    assign read_reg2_data = register_file[read_reg2_index];
    assign read_reg3_data = register_file[read_reg3_index];

    always @ (posedge clock) begin
        if (write) begin
            $display("Writing %08x into reg %01x", write_data, write_index);
            register_file[write_index] <= write_data;
        end else if (write_immediate) begin
            $display("Writing immediate %04x type %02b into reg %01x", write_immediate_data,
                write_immediate_type, write_index);
            case (write_immediate_type)
                IT_TOP:
                    register_file[write_index][31:16] <= write_immediate_data;
                IT_BOTTOM:
                    register_file[write_index][15:0] <= write_immediate_data;
                IT_SIGNED:
                    register_file[write_index] <= { { 16 { write_immediate_data[15] }}, write_immediate_data };
                IT_UNSIGNED:
                    register_file[write_index] <= { 16'h0, write_immediate_data };
            endcase
        end
    end
endmodule

module program_counter
    (
        input   reset,
        input   clock,

        input   jump,
        input   inc,
        input   [31:0] jump_data,
        output  [31:0] read_data
    );

    reg [31:0] program_counter;

    assign read_data = program_counter;

    always @ (posedge clock) begin
        if (reset) begin
            program_counter <= 32'h0;
        end else begin
            if (jump) begin
                $display("Jumping to %08x", jump_data);
                program_counter <= jump_data;
            end else if (inc) begin
                $display("Program Counter inc");
                program_counter <= program_counter + 4;
            end
        end
    end
endmodule

module status_register
    (
        input   reset,
        input   clock,

        input   write,
        input   carry_data, zero_data, neg_data, over_data,
        output  read_carry, read_zero, read_neg, read_over
    );

    reg carry, zero, neg, over;

    assign read_carry = carry;
    assign read_zero = zero;
    assign read_neg = neg;
    assign read_over = over;

    always @ (posedge clock) begin
        if (reset) begin
            carry <= 1'b0; zero <= 1'b0; neg <= 1'b0; over <= 1'b0;
        end else begin
            if (write) begin
                $display("Setting status register: CARRY: %01b ZERO: %01b NEG: %01b OVER: %01b",
                    carry, zero, neg, over);
                carry <= carry_data;
                zero <= zero_data;
                neg <= neg_data;
                over <= over_data;
            end
        end
    end
endmodule
