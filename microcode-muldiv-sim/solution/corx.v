// CORX (Core Multiply) RTL module — Intel 8086 microcode shift-and-add engine

`timescale 1ns/1ps

module corx(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    input  wire [15:0] multiplier,
    input  wire [15:0] multiplicand,
    output reg  [15:0] result_high,
    output reg  [15:0] result_low,
    output reg         done
);

    reg [15:0] tmpA;
    reg [15:0] tmpB;
    reg [15:0] tmpC;
    reg        cf;
    reg  [4:0] cnt;

    localparam S_IDLE = 3'd0,
               S_INIT = 3'd1,
               S_LOOP = 3'd2,
               S_DONE = 3'd3;
    reg [2:0] state;

    // Combinational: one complete CORX loop iteration
    // Step 1: conditional add (if cf was set by previous multiplier bit)
    wire        do_add       = cf;
    wire [16:0] sum          = {1'b0, tmpA} + {1'b0, tmpB};
    wire [15:0] after_add    = do_add ? sum[15:0] : tmpA;
    wire        cf_after_add = do_add ? sum[16]   : 1'b0;

    // Step 2: RCR tmpA — rotate right through carry
    wire [15:0] rcr_a       = {cf_after_add, after_add[15:1]};
    wire        cf_after_rcr_a = after_add[0];

    // Step 3: RCR tmpC — picks up bit shifted out of tmpA,
    //         shifts next multiplier bit into CF
    wire [15:0] rcr_c          = {cf_after_rcr_a, tmpC[15:1]};
    wire        cf_after_rcr_c = tmpC[0];

    always @(posedge clk) begin
        if (!rst_n) begin
            state       <= S_IDLE;
            done        <= 1'b0;
            tmpA        <= 16'd0;
            tmpB        <= 16'd0;
            tmpC        <= 16'd0;
            cf          <= 1'b0;
            cnt         <= 5'd0;
            result_high <= 16'd0;
            result_low  <= 16'd0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (start) begin
                        done  <= 1'b0;
                        tmpA  <= 16'd0;
                        tmpB  <= multiplicand;
                        tmpC  <= multiplier;
                        cf    <= 1'b0;
                        state <= S_INIT;
                    end
                end

                S_INIT: begin
                    // Initial RCR of tmpC with CF=0 to extract first multiplier bit
                    tmpC  <= {cf, tmpC[15:1]};
                    cf    <= tmpC[0];
                    cnt   <= 5'd15;
                    state <= S_LOOP;
                end

                S_LOOP: begin
                    tmpA <= rcr_a;
                    tmpC <= rcr_c;
                    cf   <= cf_after_rcr_c;

                    if (cnt == 5'd0) begin
                        result_high <= rcr_a;
                        result_low  <= rcr_c;
                        state       <= S_DONE;
                    end else begin
                        cnt <= cnt - 5'd1;
                    end
                end

                S_DONE: begin
                    done  <= 1'b1;
                    state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
