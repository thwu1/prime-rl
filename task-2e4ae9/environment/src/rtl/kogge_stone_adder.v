// Kogge-Stone Parallel Prefix Adder

module kogge_stone_adder #(parameter WIDTH = 8)(
    input  [WIDTH-1:0] a,
    input  [WIDTH-1:0] b,
    input              cin,
    output [WIDTH-1:0] sum,
    output             cout
);
    // Pre-computation: bit-level generate and propagate
    wire [WIDTH-1:0] p0, g0;
    assign p0 = a ^ b;
    assign g0 = a & b;

    // Fold carry-in into position 0 generate
    wire [WIDTH-1:0] g0c;
    assign g0c[0] = g0[0] | (p0[0] & cin);
    assign g0c[WIDTH-1:1] = g0[WIDTH-1:1];

    // ---- Stage 1: offset = 1 ----
    wire [WIDTH-1:0] g1, p1;
    assign g1[0] = g0c[0];
    assign p1[0] = p0[0];

    genvar i;
    generate
        for (i = 1; i < WIDTH; i = i + 1) begin : stage1
            assign g1[i] = g0c[i] | (p0[i] & g0c[i-1]);
            assign p1[i] = p0[i] & p0[i-1];
        end
    endgenerate

    // ---- Stage 2: offset = 2 ----
    wire [WIDTH-1:0] g2, p2;
    assign g2[0] = g1[0]; assign p2[0] = p1[0];
    assign g2[1] = g1[1]; assign p2[1] = p1[1];

    generate
        for (i = 2; i < WIDTH; i = i + 1) begin : stage2
            assign g2[i] = g1[i] | (p0[i] & g1[i-2]);
            assign p2[i] = p1[i] & p1[i-2];
        end
    endgenerate

    // ---- Stage 3: offset = 4 ----
    wire [WIDTH-1:0] g3, p3;
    assign g3[0] = g2[0]; assign p3[0] = p2[0];
    assign g3[1] = g2[1]; assign p3[1] = p2[1];
    assign g3[2] = g2[2]; assign p3[2] = p2[2];
    assign g3[3] = g2[3]; assign p3[3] = p2[3];

    generate
        for (i = 4; i < WIDTH; i = i + 1) begin : stage3
            assign g3[i] = g2[i] | (p2[i] & g2[i-4]);
            assign p3[i] = p2[i] & p2[i-4];
        end
    endgenerate

    // Post-computation: sum = p XOR carry_in_to_this_bit
    assign sum[0] = p0[0] ^ cin;
    generate
        for (i = 1; i < WIDTH; i = i + 1) begin : post
            assign sum[i] = p0[i] ^ g3[i-1];
        end
    endgenerate

    assign cout = g3[WIDTH-1];
endmodule
