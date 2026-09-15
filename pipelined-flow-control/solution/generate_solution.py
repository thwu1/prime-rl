#!/usr/bin/env python3

"""
Analyze arithmetic block pipeline latencies from source code and generate
a correct pipelined compute.sv with credit-based flow control.
"""

import re
import sys
import math

ARITH_DIR = "/app/arithmetic_blocks"
OUTPUT    = "/app/compute.sv"
WIDTH     = 32


def parse_localparams(filepath):
    """Extract integer-valued localparam definitions from a SV file."""
    params = {}
    with open(filepath) as f:
        for line in f:
            m = re.match(r'\s*localparam\s+(\w+)\s*=\s*(\d+)\s*;', line)
            if m:
                params[m.group(1)] = int(m.group(2))
    return params


def get_add_latency():
    p = parse_localparams(f"{ARITH_DIR}/pipe_add.sv")
    cla_bits = p["CLA_GROUP_BITS"]
    num_groups = (WIDTH + cla_bits - 1) // cla_bits
    retime = p["OUTPUT_RETIME"]
    depth = num_groups + retime
    return depth


def get_sub_latency():
    p = parse_localparams(f"{ARITH_DIR}/pipe_sub.sv")
    bpg_bits = p["BPG_GROUP_BITS"]
    num_groups = (WIDTH + bpg_bits - 1) // bpg_bits
    retime = p["OUTPUT_RETIME"]
    depth = num_groups + retime
    return depth


def get_mult_latency():
    p = parse_localparams(f"{ARITH_DIR}/pipe_mult.sv")
    radix = p["RADIX_BITS"]
    partials = (WIDTH + radix - 1) // radix
    compress = p["COMPRESS_STAGES"]
    depth = partials + compress
    return depth


def get_isqrt_latency():
    p = parse_localparams(f"{ARITH_DIR}/pipe_isqrt.sv")
    result_w = (WIDTH + 1) // 2
    bpi = p["BITS_PER_ITER"]
    stages = result_w // bpi
    return stages


def next_pow2(n):
    """Smallest power of 2 strictly greater than n."""
    p = 1
    while p <= n:
        p *= 2
    return p


def generate(add_l, sub_l, mult_l, isqrt_l):
    """Generate the complete compute.sv content."""

    # Pipeline schedule
    # Cycle 0           : inputs arrive
    # Cycle mult_l      : a*a, b*b, a*b ready
    # Cycle mult_l+add_l: a*a + b*b ready
    # Cycle mult_l+add_l+isqrt_l: isqrt ready
    # Cycle mult_l+add_l+isqrt_l+add_l: isqrt + a*b ready
    # Cycle mult_l+add_l+isqrt_l+add_l+sub_l: final result ready

    ab_delay  = add_l + isqrt_l                         # shift-reg for a*b
    c_delay   = mult_l + add_l + isqrt_l + add_l        # shift-reg for c
    total_lat = mult_l + add_l + isqrt_l + add_l + sub_l

    fifo_depth = next_pow2(total_lat)
    fifo_addr  = int(math.log2(fifo_depth))
    credit_bits = fifo_addr + 1  # enough bits to hold 0..fifo_depth

    return f"""\
// Auto-generated pipelined compute module with credit-based flow control.
// Pipeline latencies: add={add_l} sub={sub_l} mult={mult_l} isqrt={isqrt_l}
// Total pipeline latency: {total_lat} cycles
// a*b delay: {ab_delay} cycles   c delay: {c_delay} cycles
// FIFO depth: {fifo_depth}

module compute (
    input  wire        clk,
    input  wire        rst,

    input  wire        arg_vld,
    output wire        arg_rdy,
    input  wire [31:0] a,
    input  wire [31:0] b,
    input  wire [31:0] c,

    output wire        res_vld,
    input  wire        res_rdy,
    output wire [31:0] res
);

    //======================================================================
    // Internal accept signal
    //======================================================================
    wire accept = arg_vld & arg_rdy;

    //======================================================================
    // Stage 1: Three parallel multiplications  (latency = {mult_l})
    //======================================================================
    wire        mult_aa_vld;
    wire [31:0] mult_aa_out;

    pipe_mult mult_aa (
        .clk(clk), .rst(rst),
        .in_vld(accept), .in_a(a), .in_b(a),
        .out_vld(mult_aa_vld), .out_result(mult_aa_out)
    );

    wire        mult_bb_vld;
    wire [31:0] mult_bb_out;

    pipe_mult mult_bb (
        .clk(clk), .rst(rst),
        .in_vld(accept), .in_a(b), .in_b(b),
        .out_vld(mult_bb_vld), .out_result(mult_bb_out)
    );

    wire        mult_ab_vld;
    wire [31:0] mult_ab_out;

    pipe_mult mult_ab (
        .clk(clk), .rst(rst),
        .in_vld(accept), .in_a(a), .in_b(b),
        .out_vld(mult_ab_vld), .out_result(mult_ab_out)
    );

    //======================================================================
    // Stage 2: add(a*a, b*b)  (latency = {add_l})
    //======================================================================
    wire        add1_vld;
    wire [31:0] add1_out;

    pipe_add add1 (
        .clk(clk), .rst(rst),
        .in_vld(mult_aa_vld), .in_a(mult_aa_out), .in_b(mult_bb_out),
        .out_vld(add1_vld), .out_result(add1_out)
    );

    //======================================================================
    // Stage 3: isqrt(a*a + b*b)  (latency = {isqrt_l})
    //======================================================================
    wire        isqrt_vld;
    wire [31:0] isqrt_out;

    pipe_isqrt isqrt_inst (
        .clk(clk), .rst(rst),
        .in_vld(add1_vld), .in_a(add1_out),
        .out_vld(isqrt_vld), .out_result(isqrt_out)
    );

    //======================================================================
    // Shift register: delay a*b by {ab_delay} cycles (from mult output)
    //======================================================================
    reg [31:0] ab_sr [0:{ab_delay - 1}];
    integer i_ab;

    always @(posedge clk) begin
        ab_sr[0] <= mult_ab_out;
        for (i_ab = 1; i_ab < {ab_delay}; i_ab = i_ab + 1)
            ab_sr[i_ab] <= ab_sr[i_ab - 1];
    end

    //======================================================================
    // Stage 4: add(isqrt, delayed a*b)  (latency = {add_l})
    //======================================================================
    wire        add2_vld;
    wire [31:0] add2_out;

    pipe_add add2 (
        .clk(clk), .rst(rst),
        .in_vld(isqrt_vld), .in_a(isqrt_out), .in_b(ab_sr[{ab_delay - 1}]),
        .out_vld(add2_vld), .out_result(add2_out)
    );

    //======================================================================
    // Shift register: delay c by {c_delay} cycles (from module input)
    //======================================================================
    reg [31:0] c_sr [0:{c_delay - 1}];
    integer i_c;

    always @(posedge clk) begin
        c_sr[0] <= c;
        for (i_c = 1; i_c < {c_delay}; i_c = i_c + 1)
            c_sr[i_c] <= c_sr[i_c - 1];
    end

    //======================================================================
    // Stage 5: sub(isqrt + a*b, delayed c)  (latency = {sub_l})
    //======================================================================
    wire        pipe_out_vld;
    wire [31:0] pipe_out_data;

    pipe_sub sub_inst (
        .clk(clk), .rst(rst),
        .in_vld(add2_vld), .in_a(add2_out), .in_b(c_sr[{c_delay - 1}]),
        .out_vld(pipe_out_vld), .out_result(pipe_out_data)
    );

    //======================================================================
    // Output FIFO  (depth = {fifo_depth}, addr bits = {fifo_addr})
    //======================================================================
    localparam FIFO_DEPTH = {fifo_depth};
    localparam FIFO_ADDR  = {fifo_addr};

    reg [31:0]         fifo_mem [0:FIFO_DEPTH-1];
    reg [FIFO_ADDR:0]  fifo_wr_ptr;
    reg [FIFO_ADDR:0]  fifo_rd_ptr;

    wire fifo_empty = (fifo_wr_ptr == fifo_rd_ptr);
    wire fifo_push  = pipe_out_vld;
    wire fifo_pop   = res_vld & res_rdy;

    always @(posedge clk) begin
        if (rst) begin
            fifo_wr_ptr <= 0;
            fifo_rd_ptr <= 0;
        end else begin
            if (fifo_push) begin
                fifo_mem[fifo_wr_ptr[FIFO_ADDR-1:0]] <= pipe_out_data;
                fifo_wr_ptr <= fifo_wr_ptr + 1;
            end
            if (fifo_pop) begin
                fifo_rd_ptr <= fifo_rd_ptr + 1;
            end
        end
    end

    assign res     = fifo_mem[fifo_rd_ptr[FIFO_ADDR-1:0]];
    assign res_vld = ~fifo_empty;

    //======================================================================
    // Credit counter for flow control
    //======================================================================
    reg [{credit_bits - 1}:0] credits;

    wire consume = res_vld & res_rdy;

    always @(posedge clk) begin
        if (rst) begin
            credits <= FIFO_DEPTH;
        end else begin
            case ({{accept, consume}})
                2'b10:   credits <= credits - 1;
                2'b01:   credits <= credits + 1;
                default: credits <= credits;
            endcase
        end
    end

    assign arg_rdy = (credits > 0);

endmodule
"""


def main():
    add_l   = get_add_latency()
    sub_l   = get_sub_latency()
    mult_l  = get_mult_latency()
    isqrt_l = get_isqrt_latency()

    total = mult_l + add_l + isqrt_l + add_l + sub_l

    print(f"Latencies discovered from source analysis:", file=sys.stderr)
    print(f"  pipe_add   : {add_l} cycles", file=sys.stderr)
    print(f"  pipe_sub   : {sub_l} cycles", file=sys.stderr)
    print(f"  pipe_mult  : {mult_l} cycles", file=sys.stderr)
    print(f"  pipe_isqrt : {isqrt_l} cycles", file=sys.stderr)
    print(f"  Total pipeline latency : {total} cycles", file=sys.stderr)
    print(f"  FIFO depth : {next_pow2(total)}", file=sys.stderr)

    sv_code = generate(add_l, sub_l, mult_l, isqrt_l)

    with open(OUTPUT, "w") as f:
        f.write(sv_code)

    print(f"\nGenerated {OUTPUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
