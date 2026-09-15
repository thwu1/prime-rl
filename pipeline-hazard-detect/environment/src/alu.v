`include "alu.vh"
`include "registers.vh"

module alu
    (
        input reset,
        input clock,
        input [4:0] op,
        input [31:0] reg2, reg3,
        input carry_in,
        output reg [31:0] result,
        output reg carry_out, zero_out, neg_out, over_out
    );

    wire [32:0] temp_reg2 = { 1'b0, reg2 };
    wire [32:0] temp_reg3 = { 1'b0, reg3 };
    wire [4:0] shift_amount = reg3[4:0];
    reg [32:0] temp_result;
    reg [31:0] temp_mul_result;
    reg give_result;

    always @ (posedge clock) begin
        if (reset) begin
            result <= 32'h0;
            carry_out <= 1'b0;
            zero_out <= 1'b0;
            neg_out <= 1'b0;
            over_out <= 1'b0;
        end else begin
            $display("ALU: op: %02x reg2: %08x reg3: %08x", op, reg2, reg3);
            temp_result = { 1'b0, 32'h0 };
            temp_mul_result = 32'h0;
            give_result = 1'b1;

            case (op)
                OP_ADD:
                    temp_result = temp_reg2 + temp_reg3;
                OP_ADDC:
                    temp_result = temp_reg2 + temp_reg3 + { 32'h0, carry_in };
                OP_SUB:
                    temp_result = temp_reg2 - temp_reg3;
                OP_SUBC:
                    temp_result = temp_reg2 - temp_reg3 - { 32'h0, carry_in };
                OP_AND:
                    temp_result = temp_reg2 & temp_reg3;
                OP_OR:
                    temp_result = temp_reg2 | temp_reg3;
                OP_XOR:
                    temp_result = temp_reg2 ^ temp_reg3;
                OP_COMP: begin
                    temp_result = temp_reg2 - temp_reg3;
                    give_result = 1'b0;
                end
                OP_BIT: begin
                    temp_result = temp_reg2 & temp_reg3;
                    give_result = 1'b0;
                end
                OP_MULU: begin
                    temp_mul_result = temp_reg2[15:0] * temp_reg3[15:0];
                    temp_result = { 1'b0, temp_mul_result };
                end
                OP_MULS: begin
                    temp_mul_result = $signed(temp_reg2[15:0]) * $signed(temp_reg3[15:0]);
                    temp_result = { 1'b0, temp_mul_result };
                end
                OP_LOGIC_LEFT:
                    temp_result = temp_reg2 << shift_amount;
                OP_LOGIC_RIGHT: begin
                    temp_result[31:0] = reg2 >> shift_amount;
                    temp_result[32] = reg2[shift_amount - 5'b00001];
                end
                OP_ARITH_LEFT:
                    // Identical except for overflow handling.
                    temp_result = temp_reg2 << shift_amount;
                OP_ARITH_RIGHT: begin
                    temp_result[31:0] = $signed(reg2) >>> shift_amount;
                    temp_result[32] = reg2[shift_amount - 5'b00001];
                end

                OP_NOT:
                    temp_result = ~{ 1'b1, temp_reg2[31:0]};
                OP_NEG:
                    temp_result = ~temp_reg2 + { 31'b0, 1'b1 };
                OP_SWAP:
                    temp_result = { 1'b0, temp_reg2[15:0], temp_reg2[31:16] };
                OP_TEST: begin
                    temp_result = temp_reg2;
                    give_result = 1'b0;
                end
                OP_SIGN_EXT_B:
                    temp_result = { 1'b0, {24{ temp_reg2[7] }}, temp_reg2[7:0] };
                OP_SIGN_EXT_W:
                    temp_result = { 1'b0, {16{ temp_reg2[15] }}, temp_reg2[15:0] };
                OP_UNSIGN_EXT_B:
                    temp_result = { 1'b0, 24'h000000, temp_reg2[7:0] };
                OP_UNSIGN_EXT_W:
                    temp_result = { 1'b0, 16'h0000, temp_reg2[15:0] };
                OP_COPY:
                    temp_result = temp_reg2;

                default:
                    temp_result = { 1'b0, 32'h0 };
            endcase

            if (give_result) begin
                result <= temp_result[31:0];
            end else begin
                // If we are doing a test or comparison, then output what was input. This will still
                // get written into a register, so possibly "give_result" is not the right name...
                result <= reg2;
            end

            carry_out <= temp_result[32];

            if (temp_result[31:0] == 32'h0) begin
                zero_out <= 1'b1;
            end else begin
                zero_out <= 1'b0;
            end

            neg_out <= temp_result[31];

            // When adding then if sign of result is different to the sign of both the
            // operands then it is an overflow condition
            if (op == OP_ADD || op == OP_ADDC) begin
                if (temp_reg3[31] != temp_result[31] && temp_reg2 [31] != temp_result[31]) begin
                    over_out <= 1'b1;
                end else begin
                    over_out <= 1'b0;
                end
            end
            // Likewise for sub, but invert the reg3 sign for test as its a subtract
            else if (op == OP_SUB || op == OP_SUBC) begin
                if (temp_reg3[31] == temp_result[31] && temp_reg2[31] != temp_result[31]) begin
                    over_out <= 1'b1;
                end else begin
                    over_out <= 1'b0;
                end
            end
            // For arith shift reg3, if the sign changed then it is an overflow
            else if (op == OP_ARITH_LEFT) begin
                if (temp_reg2[31] != temp_result[31]) begin
                    over_out <= 1'b1;
                end else begin
                    over_out <= 1'b0;
                end
            end else begin
                over_out <= 1'b0;
            end
        end
    end

endmodule
