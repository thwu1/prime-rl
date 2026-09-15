module alu (
    input  wire [31:0] a,
    input  wire [31:0] b,
    input  wire [3:0]  op,
    output reg  [31:0] result
);

    always @(*) begin
        case (op)
            4'b0000: result = a + b;
            4'b0001: result = a - b;
            4'b0010: result = a << b[4:0];
            4'b0011: result = ($signed(a) < $signed(b)) ? 32'd1 : 32'd0;
            4'b0100: result = (a < b) ? 32'd1 : 32'd0;
            4'b0101: result = a ^ b;
            4'b0110: result = a >> b[4:0];
            4'b0111: result = $signed(a) >>> b[4:0];
            4'b1000: result = a | b;
            4'b1001: result = a & b;
            default: result = 32'b0;
        endcase
    end

endmodule
