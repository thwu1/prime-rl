`default_nettype none
`timescale 1ns/1ns

// REGISTER FILE
// > 13 free registers (R0-R12) and 3 read-only registers (%blockIdx, %blockDim, %threadIdx)
module registers #(
    parameter THREADS_PER_BLOCK = 4,
    parameter THREAD_ID = 0,
    parameter DATA_BITS = 8
) (
    input wire clk,
    input wire reset,
    input wire enable,
    input reg [7:0] block_id,
    input reg [2:0] core_state,
    input reg [3:0] decoded_rd_address,
    input reg [3:0] decoded_rs_address,
    input reg [3:0] decoded_rt_address,
    input reg decoded_reg_write_enable,
    input reg [1:0] decoded_reg_input_mux,
    input reg [DATA_BITS-1:0] decoded_immediate,
    input reg [DATA_BITS-1:0] alu_out,
    input reg [DATA_BITS-1:0] lsu_out,
    output reg [7:0] rs,
    output reg [7:0] rt
);
    localparam ARITHMETIC = 2'b00, MEMORY = 2'b01, CONSTANT = 2'b10;
    reg [7:0] registers[15:0];

    always @(posedge clk) begin
        if (reset) begin
            rs <= 0; rt <= 0;
            for (int i = 0; i < 13; i++) registers[i] <= 8'b0;
            registers[13] <= 8'b0;              // %blockIdx
            registers[14] <= THREADS_PER_BLOCK;  // %blockDim
            registers[15] <= THREAD_ID;          // %threadIdx
        end else if (enable) begin
            registers[13] <= block_id;
            if (core_state == 3'b011) begin // REQUEST
                rs <= registers[decoded_rs_address];
                rt <= registers[decoded_rt_address];
            end
            if (core_state == 3'b110) begin // UPDATE
                if (decoded_reg_write_enable && decoded_rd_address < 13) begin
                    case (decoded_reg_input_mux)
                        ARITHMETIC: registers[decoded_rd_address] <= alu_out;
                        MEMORY: registers[decoded_rd_address] <= lsu_out;
                        CONSTANT: registers[decoded_rd_address] <= decoded_immediate;
                    endcase
                end
            end
        end
    end
endmodule
