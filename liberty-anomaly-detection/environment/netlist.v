/* Gate-level netlist: 4-bit pipelined ripple carry adder */
/* Synthesized with minimum optimization — has long carry chain */

module adder_pipe (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [3:0] a,
    input  wire [3:0] b,
    output wire [3:0] sum,
    output wire       cout
);

    wire a0_r, a1_r, a2_r, a3_r;
    wire b0_r, b1_r, b2_r, b3_r;

    /* ── Stage-1 input registers ───────────────────────── */
    DFFR_X1 ff_a0 (.D(a[0]), .CLK(clk), .RST(rst_n), .Q(a0_r), .QN());
    DFFR_X1 ff_a1 (.D(a[1]), .CLK(clk), .RST(rst_n), .Q(a1_r), .QN());
    DFFR_X1 ff_a2 (.D(a[2]), .CLK(clk), .RST(rst_n), .Q(a2_r), .QN());
    DFFR_X1 ff_a3 (.D(a[3]), .CLK(clk), .RST(rst_n), .Q(a3_r), .QN());
    DFFR_X1 ff_b0 (.D(b[0]), .CLK(clk), .RST(rst_n), .Q(b0_r), .QN());
    DFFR_X1 ff_b1 (.D(b[1]), .CLK(clk), .RST(rst_n), .Q(b1_r), .QN());
    DFFR_X1 ff_b2 (.D(b[2]), .CLK(clk), .RST(rst_n), .Q(b2_r), .QN());
    DFFR_X1 ff_b3 (.D(b[3]), .CLK(clk), .RST(rst_n), .Q(b3_r), .QN());

    /* ── 4-bit ripple carry adder (cin=0) ──────────────── */
    /* Bit 0: sum0 = a0 XOR b0, c0 = a0 AND b0 */
    wire p0, c0;
    XOR2_X1 xor_p0 (.A(a0_r), .B(b0_r), .Y(p0));
    AND2_X1 and_g0 (.A(a0_r), .B(b0_r), .Y(c0));

    /* Bit 1: sum1 = a1 XOR b1 XOR c0, c1 = (a1 AND b1) OR (c0 AND (a1 XOR b1)) */
    wire p1, g1, pc1, c1, s1;
    XOR2_X1 xor_p1  (.A(a1_r),  .B(b1_r), .Y(p1));
    AND2_X1 and_g1  (.A(a1_r),  .B(b1_r), .Y(g1));
    AND2_X1 and_pc1 (.A(c0),    .B(p1),   .Y(pc1));
    OR2_X1  or_c1   (.A(g1),    .B(pc1),  .Y(c1));
    XOR2_X1 xor_s1  (.A(p1),    .B(c0),   .Y(s1));

    /* Bit 2: sum2 = a2 XOR b2 XOR c1, c2 = (a2 AND b2) OR (c1 AND (a2 XOR b2)) */
    wire p2, g2, pc2, c2, s2;
    XOR2_X1 xor_p2  (.A(a2_r),  .B(b2_r), .Y(p2));
    AND2_X1 and_g2  (.A(a2_r),  .B(b2_r), .Y(g2));
    AND2_X1 and_pc2 (.A(c1),    .B(p2),   .Y(pc2));
    OR2_X1  or_c2   (.A(g2),    .B(pc2),  .Y(c2));
    XOR2_X1 xor_s2  (.A(p2),    .B(c1),   .Y(s2));

    /* Bit 3: sum3 = a3 XOR b3 XOR c2, cout = (a3 AND b3) OR (c2 AND (a3 XOR b3)) */
    wire p3, g3, pc3, c3, s3;
    XOR2_X1 xor_p3  (.A(a3_r),  .B(b3_r), .Y(p3));
    AND2_X1 and_g3  (.A(a3_r),  .B(b3_r), .Y(g3));
    AND2_X1 and_pc3 (.A(c2),    .B(p3),   .Y(pc3));
    OR2_X1  or_c3   (.A(g3),    .B(pc3),  .Y(c3));
    XOR2_X1 xor_s3  (.A(p3),    .B(c2),   .Y(s3));

    /* ── Stage-2 output registers ──────────────────────── */
    DFFR_X1 ff_s0 (.D(p0), .CLK(clk), .RST(rst_n), .Q(sum[0]), .QN());
    DFFR_X1 ff_s1 (.D(s1), .CLK(clk), .RST(rst_n), .Q(sum[1]), .QN());
    DFFR_X1 ff_s2 (.D(s2), .CLK(clk), .RST(rst_n), .Q(sum[2]), .QN());
    DFFR_X1 ff_s3 (.D(s3), .CLK(clk), .RST(rst_n), .Q(sum[3]), .QN());
    DFFR_X1 ff_co (.D(c3), .CLK(clk), .RST(rst_n), .Q(cout),   .QN());

endmodule
