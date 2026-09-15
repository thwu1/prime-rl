// Sklansky (Zero-Deficiency) Parallel Prefix Adder — Correct Implementation

module sklansky_adder #(parameter WIDTH = 8)(
    input  [WIDTH-1:0] a,
    input  [WIDTH-1:0] b,
    input              cin,
    output [WIDTH-1:0] sum,
    output             cout
);
    wire [WIDTH-1:0] p, g;
    assign p = a ^ b;
    assign g = a & b;

    // Fold carry-in into position 0 generate
    wire [WIDTH-1:0] G0, P0;
    assign G0[0] = g[0] | (p[0] & cin);
    assign G0[WIDTH-1:1] = g[WIDTH-1:1];
    assign P0 = p;

    // ==== Level 0 (k=0): block size 2, odd positions combine with even ====
    wire [WIDTH-1:0] G1, P1;
    assign G1[0] = G0[0]; assign P1[0] = P0[0];
    assign G1[2] = G0[2]; assign P1[2] = P0[2];
    assign G1[4] = G0[4]; assign P1[4] = P0[4];
    assign G1[6] = G0[6]; assign P1[6] = P0[6];

    assign G1[1] = G0[1] | (P0[1] & G0[0]);
    assign P1[1] = P0[1] & P0[0];
    assign G1[3] = G0[3] | (P0[3] & G0[2]);
    assign P1[3] = P0[3] & P0[2];
    assign G1[5] = G0[5] | (P0[5] & G0[4]);
    assign P1[5] = P0[5] & P0[4];
    assign G1[7] = G0[7] | (P0[7] & G0[6]);
    assign P1[7] = P0[7] & P0[6];

    // ==== Level 1 (k=1): block size 4 ====
    // Positions 0,1 pass through; 2,3 combine with pos 1; 4,5 pass; 6,7 combine with 5
    wire [WIDTH-1:0] G2, P2;
    assign G2[0] = G1[0]; assign P2[0] = P1[0];
    assign G2[1] = G1[1]; assign P2[1] = P1[1];
    assign G2[4] = G1[4]; assign P2[4] = P1[4];
    assign G2[5] = G1[5]; assign P2[5] = P1[5];

    assign G2[2] = G1[2] | (P1[2] & G1[1]);
    assign P2[2] = P1[2] & P1[1];
    assign G2[3] = G1[3] | (P1[3] & G1[1]);
    assign P2[3] = P1[3] & P1[1];
    assign G2[6] = G1[6] | (P1[6] & G1[5]);
    assign P2[6] = P1[6] & P1[5];
    assign G2[7] = G1[7] | (P1[7] & G1[5]);
    assign P2[7] = P1[7] & P1[5];

    // ==== Level 2 (k=2): block size 8 ====
    // Positions 0-3 pass through; 4-7 combine with pos 3
    wire [WIDTH-1:0] G3, P3;
    assign G3[0] = G2[0]; assign P3[0] = P2[0];
    assign G3[1] = G2[1]; assign P3[1] = P2[1];
    assign G3[2] = G2[2]; assign P3[2] = P2[2];
    assign G3[3] = G2[3]; assign P3[3] = P2[3];

    assign G3[4] = G2[4] | (P2[4] & G2[3]);
    assign P3[4] = P2[4] & P2[3];
    assign G3[5] = G2[5] | (P2[5] & G2[3]);
    assign P3[5] = P2[5] & P2[3];
    assign G3[6] = G2[6] | (P2[6] & G2[3]);
    assign P3[6] = P2[6] & P2[3];
    assign G3[7] = G2[7] | (P2[7] & G2[3]);
    assign P3[7] = P2[7] & P2[3];

    // ==== Post-computation ====
    assign sum[0] = p[0] ^ cin;
    genvar i;
    generate
        for (i = 1; i < WIDTH; i = i + 1) begin : post
            assign sum[i] = p[i] ^ G3[i-1];
        end
    endgenerate

    assign cout = G3[WIDTH-1];
endmodule
