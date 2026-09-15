/* Verilog simulation models for synth_45nm standard cells */
/* For use with iverilog gate-level simulation */

`timescale 1ns/1ps

module INV_X1 (input A, output Y);
    assign Y = ~A;
endmodule

module INV_X2 (input A, output Y);
    assign Y = ~A;
endmodule

module BUF_X1 (input A, output Y);
    assign Y = A;
endmodule

module NAND2_X1 (input A, input B, output Y);
    assign Y = ~(A & B);
endmodule

module NOR2_X1 (input A, input B, output Y);
    assign Y = ~(A | B);
endmodule

module AND2_X1 (input A, input B, output Y);
    assign Y = A & B;
endmodule

module OR2_X1 (input A, input B, output Y);
    assign Y = A | B;
endmodule

module XOR2_X1 (input A, input B, output Y);
    assign Y = A ^ B;
endmodule

module DFFR_X1 (input D, input CLK, input RST, output reg Q, output QN);
    assign QN = ~Q;
    always @(posedge CLK or negedge RST) begin
        if (!RST)
            Q <= 1'b0;
        else
            Q <= D;
    end
endmodule
