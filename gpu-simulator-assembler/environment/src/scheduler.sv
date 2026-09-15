`default_nettype none
`timescale 1ns/1ns

// SCHEDULER
// > Manages the control flow of a single compute core processing 1 block
// Pipeline stages: FETCH -> DECODE -> REQUEST -> WAIT -> EXECUTE -> UPDATE
module scheduler #(
    parameter THREADS_PER_BLOCK = 4,
) (
    input wire clk,
    input wire reset,
    input wire start,
    input reg decoded_mem_read_enable,
    input reg decoded_mem_write_enable,
    input reg decoded_ret,
    input reg [2:0] fetcher_state,
    input reg [1:0] lsu_state [THREADS_PER_BLOCK-1:0],
    output reg [7:0] current_pc,
    input reg [7:0] next_pc [THREADS_PER_BLOCK-1:0],
    output reg [2:0] core_state,
    output reg done
);
    localparam IDLE = 3'b000, FETCH = 3'b001, DECODE = 3'b010,
        REQUEST = 3'b011, WAIT = 3'b100, EXECUTE = 3'b101,
        UPDATE = 3'b110, DONE = 3'b111;

    always @(posedge clk) begin
        if (reset) begin
            current_pc <= 0; core_state <= IDLE; done <= 0;
        end else begin
            case (core_state)
                IDLE: if (start) core_state <= FETCH;
                FETCH: if (fetcher_state == 3'b010) core_state <= DECODE;
                DECODE: core_state <= REQUEST;
                REQUEST: core_state <= WAIT;
                WAIT: begin
                    reg any_lsu_waiting = 1'b0;
                    for (int i = 0; i < THREADS_PER_BLOCK; i++) begin
                        if (lsu_state[i] == 2'b01 || lsu_state[i] == 2'b10) begin
                            any_lsu_waiting = 1'b1; break;
                        end
                    end
                    if (!any_lsu_waiting) core_state <= EXECUTE;
                end
                EXECUTE: core_state <= UPDATE;
                UPDATE: begin
                    if (decoded_ret) begin
                        done <= 1; core_state <= DONE;
                    end else begin
                        current_pc <= next_pc[THREADS_PER_BLOCK-1];
                        core_state <= FETCH;
                    end
                end
                DONE: begin end
            endcase
        end
    end
endmodule
