`default_nettype none
`timescale 1ns/1ns

// PROGRAM COUNTER
// > Calculates the next PC for each thread
// > NZP register is set by CMP and checked by BRnzp for branching
module pc #(
    parameter DATA_MEM_DATA_BITS = 8,
    parameter PROGRAM_MEM_ADDR_BITS = 8
) (
    input wire clk,
    input wire reset,
    input wire enable,
    input reg [2:0] core_state,
    input reg [2:0] decoded_nzp,
    input reg [DATA_MEM_DATA_BITS-1:0] decoded_immediate,
    input reg decoded_nzp_write_enable,
    input reg decoded_pc_mux,
    input reg [DATA_MEM_DATA_BITS-1:0] alu_out,
    input reg [PROGRAM_MEM_ADDR_BITS-1:0] current_pc,
    output reg [PROGRAM_MEM_ADDR_BITS-1:0] next_pc
);
    reg [2:0] nzp;

    always @(posedge clk) begin
        if (reset) begin
            nzp <= 3'b0; next_pc <= 0;
        end else if (enable) begin
            if (core_state == 3'b101) begin // EXECUTE
                if (decoded_pc_mux == 1) begin
                    if ((nzp & decoded_nzp) != 3'b0)
                        next_pc <= decoded_immediate;
                    else
                        next_pc <= current_pc + 1;
                end else begin
                    next_pc <= current_pc + 1;
                end
            end
            if (core_state == 3'b110) begin // UPDATE
                if (decoded_nzp_write_enable) begin
                    nzp[2] <= alu_out[2];
                    nzp[1] <= alu_out[1];
                    nzp[0] <= alu_out[0];
                end
            end
        end
    end
endmodule
