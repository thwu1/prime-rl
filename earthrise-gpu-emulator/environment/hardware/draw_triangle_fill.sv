// Project F Library - Draw Filled Triangle
// (C)2021 Will Green, open source hardware released under the MIT License
// Learn more at https://projectf.io

// Edge function rasterization: iterates over bounding box,
// testing point-in-triangle via half-plane intersection.

`default_nettype none
`timescale 1ns / 1ps

module draw_triangle_fill #(parameter CORDW=16) (  // signed coordinate width
    input  wire logic clk,             // clock
    input  wire logic rst,             // reset
    input  wire logic start,           // start triangle fill
    input  wire logic oe,              // output enable
    input  wire logic signed [CORDW-1:0] x0, y0,  // vertex 0
    input  wire logic signed [CORDW-1:0] x1, y1,  // vertex 1
    input  wire logic signed [CORDW-1:0] x2, y2,  // vertex 2
    output      logic signed [CORDW-1:0] x,  y,   // drawing position
    output      logic drawing,         // actively drawing
    output      logic busy,            // drawing request in progress
    output      logic done             // drawing is complete (high for one tick)
    );

    localparam EW = 2*CORDW+2;  // edge function width (products + sign)

    // edge function increments for stepping across the bounding box
    //   x-step: a_ij = y_i - y_j
    //   y-step: b_ij = x_j - x_i
    logic signed [CORDW:0] sa01, sa12, sa20;
    logic signed [CORDW:0] sb01, sb12, sb20;

    // edge function values at current pixel
    logic signed [EW-1:0] w0, w1, w2;

    // edge function values saved at start of each row
    logic signed [EW-1:0] w0_row, w1_row, w2_row;

    // bounding box
    logic signed [CORDW-1:0] bbx0, bby0, bbx1, bby1;

    // scan position
    logic signed [CORDW-1:0] sx, sy;

    // winding order: true if clockwise
    logic cw;

    // half-plane inside test (handles both CW and CCW winding)
    wire inside = cw ? (w0 <= 0 && w1 <= 0 && w2 <= 0)
                      : (w0 >= 0 && w1 >= 0 && w2 >= 0);

    // three-way min/max combinational helpers
    wire signed [CORDW-1:0] min_x01 = (x0 < x1) ? x0 : x1;
    wire signed [CORDW-1:0] max_x01 = (x0 > x1) ? x0 : x1;
    wire signed [CORDW-1:0] min_y01 = (y0 < y1) ? y0 : y1;
    wire signed [CORDW-1:0] max_y01 = (y0 > y1) ? y0 : y1;

    // draw state machine
    enum {IDLE, INIT, EVAL, SCAN} state;
    always_comb drawing = (state == SCAN && oe && inside);

    always_ff @(posedge clk) begin
        case (state)
            INIT: begin
                state <= EVAL;
                // x-step increments for edge functions
                sa01 <= y0 - y1;
                sa12 <= y1 - y2;
                sa20 <= y2 - y0;
                // y-step increments for edge functions
                sb01 <= x1 - x0;
                sb12 <= x2 - x1;
                sb20 <= x0 - x2;
                // bounding box
                bbx0 <= (min_x01 < x2) ? min_x01 : x2;
                bby0 <= (min_y01 < y2) ? min_y01 : y2;
                bbx1 <= (max_x01 > x2) ? max_x01 : x2;
                bby1 <= (max_y01 > y2) ? max_y01 : y2;
                // winding: cross product of edge vectors
                /* verilator lint_off WIDTH */
                cw <= ((x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)) < 0;
                /* verilator lint_on WIDTH */
            end
            EVAL: begin
                state <= SCAN;
                // compute initial edge functions at bounding box origin
                /* verilator lint_off WIDTH */
                w0 <= (bbx0 - x0) * sa01 + (bby0 - y0) * sb01;
                w1 <= (bbx0 - x1) * sa12 + (bby0 - y1) * sb12;
                w2 <= (bbx0 - x2) * sa20 + (bby0 - y2) * sb20;
                w0_row <= (bbx0 - x0) * sa01 + (bby0 - y0) * sb01;
                w1_row <= (bbx0 - x1) * sa12 + (bby0 - y1) * sb12;
                w2_row <= (bbx0 - x2) * sa20 + (bby0 - y2) * sb20;
                /* verilator lint_on WIDTH */
                sx <= bbx0;
                sy <= bby0;
                x <= bbx0;
                y <= bby0;
            end
            SCAN: begin
                if (oe) begin
                    if (sx == bbx1) begin
                        if (sy == bby1) begin
                            state <= IDLE;
                            busy <= 0;
                            done <= 1;
                        end else begin
                            // advance to next scanline
                            sy <= sy + 1;
                            y <= sy + 1;
                            sx <= bbx0;
                            x <= bbx0;
                            w0 <= w0_row + sb01;
                            w1 <= w1_row + sb12;
                            w2 <= w2_row + sb20;
                            w0_row <= w0_row + sb01;
                            w1_row <= w1_row + sb12;
                            w2_row <= w2_row + sb20;
                        end
                    end else begin
                        // advance to next pixel in row
                        sx <= sx + 1;
                        x <= sx + 1;
                        w0 <= w0 + sa01;
                        w1 <= w1 + sa12;
                        w2 <= w2 + sa20;
                    end
                end
            end
            default: begin  // IDLE
                done <= 0;
                if (start) begin
                    state <= INIT;
                    busy <= 1;
                end
            end
        endcase

        if (rst) begin
            state <= IDLE;
            busy <= 0;
            done <= 0;
        end
    end
endmodule
