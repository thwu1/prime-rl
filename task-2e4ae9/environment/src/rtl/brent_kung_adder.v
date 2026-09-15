// Brent-Kung Parallel Prefix Adder

module brent_kung_adder #(parameter WIDTH = 8)(
    input  [WIDTH-1:0] a,
    input  [WIDTH-1:0] b,
    input              cin,
    output [WIDTH-1:0] sum,
    output             cout
);
    wire [WIDTH-1:0] p, g;
    assign p = a ^ b;
    assign g = a & b;

    // Fold carry-in into position 0
    wire [WIDTH-1:0] G0, P0;
    assign G0[0] = g[0] | (p[0] & cin);
    assign G0[WIDTH-1:1] = g[WIDTH-1:1];
    assign P0 = p;

    // ==== Forward reduction tree ====

    // Level 1 (offset 1): odd positions pair with even predecessors
    wire G_1_0, P_1_0;
    assign G_1_0 = G0[1] | (P0[1] & G0[0]);
    assign P_1_0 = P0[1] & P0[0];

    wire G_3_2, P_3_2;
    assign G_3_2 = G0[3] | (P0[3] & G0[2]);
    assign P_3_2 = P0[3] & P0[2];

    wire G_5_4, P_5_4;
    assign G_5_4 = G0[5] | (P0[5] & G0[4]);
    assign P_5_4 = P0[5] & P0[4];

    wire G_7_6, P_7_6;
    assign G_7_6 = G0[7] | (P0[7] & G0[6]);
    assign P_7_6 = P0[7] & P0[6];

    // Level 2 (offset 2): positions 3, 7
    wire G_3_0, P_3_0;
    assign G_3_0 = G_3_2 | (P_3_2 & G_1_0);
    assign P_3_0 = P_3_2 & P_1_0;

    wire G_7_4, P_7_4;
    assign G_7_4 = G_7_6 | (P_7_6 & G_5_4);
    assign P_7_4 = P_7_6 & P_5_4;

    // Level 3 (offset 4): position 7 only
    wire G_7_0, P_7_0;
    assign G_7_0 = G_7_4 | (P_7_4 & G_3_0);
    assign P_7_0 = P_7_4 & P_3_0;

    // ==== Backward propagation ====

    // Back level 1: position 5 combines with prefix through position 3
    wire G_5_0, P_5_0;
    assign G_5_0 = G_5_4 | (P_5_4 & G_3_0);
    assign P_5_0 = P_5_4 & P_3_0;

    // Back level 2: remaining even positions
    wire G_2_0;
    assign G_2_0 = G0[2] | (P0[2] & G_1_0);

    wire G_4_0;
    assign G_4_0 = G0[4] | (P0[4] & G_3_0);

    wire G_6_0;
    assign G_6_0 = G0[6] | (P0[6] & G_3_0);

    // ==== Carry assignment ====
    wire [WIDTH-1:0] carry;
    assign carry[0] = G0[0];
    assign carry[1] = G_1_0;
    assign carry[2] = G_2_0;
    assign carry[3] = G_3_0;
    assign carry[4] = G_4_0;
    assign carry[5] = G_5_0;
    assign carry[6] = G_6_0;
    assign carry[7] = G_7_0;

    // ==== Post-computation ====
    assign sum[0] = p[0] ^ cin;
    genvar i;
    generate
        for (i = 1; i < WIDTH; i = i + 1) begin : post
            assign sum[i] = p[i] ^ carry[i-1];
        end
    endgenerate

    assign cout = carry[WIDTH-1];
endmodule
