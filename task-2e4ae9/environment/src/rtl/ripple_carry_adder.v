// Ripple Carry Adder - Reference Implementation

module ripple_carry_adder #(parameter WIDTH = 8)(
    input  [WIDTH-1:0] a,
    input  [WIDTH-1:0] b,
    input              cin,
    output [WIDTH-1:0] sum,
    output             cout
);
    wire [WIDTH:0] c;
    assign c[0] = cin;

    genvar i;
    generate
        for (i = 0; i < WIDTH; i = i + 1) begin : bit
            assign sum[i]  = a[i] ^ b[i] ^ c[i];
            assign c[i+1]  = (a[i] & b[i]) | (a[i] & c[i]) | (b[i] & c[i]);
        end
    endgenerate

    assign cout = c[WIDTH];
endmodule
