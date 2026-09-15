#!/usr/bin/env python3
"""
Solve the hardware arithmetic verification + Mandelbrot task using Icarus Verilog
simulation for the arithmetic modules and Python for the Mandelbrot computation.

"""

import subprocess
import json
import os
import sys


# ============================================================================
# Utility
# ============================================================================

def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)


def run_cmd(cmd, cwd="/app"):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        print(f"Command failed: {cmd}", file=sys.stderr)
        print(f"STDOUT: {result.stdout}", file=sys.stderr)
        print(f"STDERR: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


# ============================================================================
# Testbench generation
# ============================================================================

def gen_tb_divu_int():
    tests = [
        (100, 7), (255, 16), (1, 1), (0, 42),
        (12345678, 9999), (999999999, 7), (4294967295, 65536), (100, 0),
    ]
    calls = "\n".join(f"        run_div(32'd{a}, 32'd{b});" for a, b in tests)
    return f"""`timescale 1ns/1ps
module tb_divu_int;
    parameter WIDTH = 32;
    reg clk, rst, start;
    wire busy, done, valid, dbz;
    reg [WIDTH-1:0] a, b;
    wire [WIDTH-1:0] val, rem;

    divu_int #(.WIDTH(WIDTH)) dut (
        .clk(clk), .rst(rst), .start(start),
        .busy(busy), .done(done), .valid(valid), .dbz(dbz),
        .a(a), .b(b), .val(val), .rem(rem)
    );

    initial clk = 0;
    always #5 clk = ~clk;

    task run_div;
        input [WIDTH-1:0] ta;
        input [WIDTH-1:0] tb;
        begin
            @(negedge clk);
            a = ta; b = tb; start = 1;
            @(posedge clk);
            @(negedge clk);
            start = 0;
            if (done) begin
                $display("DIV %0d %0d %0d %0d %0d", ta, tb, val, rem, dbz);
            end else begin
                while (!done) begin
                    @(posedge clk);
                    @(negedge clk);
                end
                $display("DIV %0d %0d %0d %0d %0d", ta, tb, val, rem, dbz);
            end
        end
    endtask

    initial begin
        rst = 1; start = 0; a = 0; b = 0;
        repeat(3) @(posedge clk);
        @(negedge clk);
        rst = 0;
{calls}
        #100;
        $finish;
    end
endmodule
"""


def gen_tb_sqrt_int():
    tests = [0, 1, 25, 144, 200, 1000000, 50000000, 4294967295]
    calls = "\n".join(f"        run_sqrt(32'd{r});" for r in tests)
    return f"""`timescale 1ns/1ps
module tb_sqrt_int;
    parameter WIDTH = 32;
    reg clk, start;
    reg [WIDTH-1:0] rad;
    wire busy, valid;
    wire [WIDTH-1:0] root, rem;

    sqrt_int #(.WIDTH(WIDTH)) dut (
        .clk(clk), .start(start),
        .busy(busy), .valid(valid),
        .rad(rad), .root(root), .rem(rem)
    );

    initial clk = 0;
    always #5 clk = ~clk;

    task run_sqrt;
        input [WIDTH-1:0] r;
        begin
            @(negedge clk);
            rad = r; start = 1;
            @(posedge clk);
            @(negedge clk);
            start = 0;
            while (!valid) begin
                @(posedge clk);
                @(negedge clk);
            end
            $display("SQRT %0d %0d %0d", r, root, rem);
        end
    endtask

    initial begin
        start = 0; rad = 0;
        repeat(2) @(posedge clk);
{calls}
        #100;
        $finish;
    end
endmodule
"""


def gen_tb_divu():
    tests_real = [(7.0, 2.0), (10.0, 4.0), (15.0, 2.0), (1.0, 3.0), (1.0, 7.0)]
    lines = []
    for a_real, b_real in tests_real:
        a_fp = int(a_real * (1 << 21))
        b_fp = int(b_real * (1 << 21))
        lines.append(f"        run_divfp(25'd{a_fp}, 25'd{b_fp});")
    calls = "\n".join(lines)
    return f"""`timescale 1ns/1ps
module tb_divu_fp;
    parameter WIDTH = 25;
    parameter FBITS = 21;
    reg clk, rst, start;
    wire busy, done, valid, dbz, ovf;
    reg [WIDTH-1:0] a, b;
    wire [WIDTH-1:0] val;

    divu #(.WIDTH(WIDTH), .FBITS(FBITS)) dut (
        .clk(clk), .rst(rst), .start(start),
        .busy(busy), .done(done), .valid(valid),
        .dbz(dbz), .ovf(ovf), .a(a), .b(b), .val(val)
    );

    initial clk = 0;
    always #5 clk = ~clk;

    task run_divfp;
        input [WIDTH-1:0] ta;
        input [WIDTH-1:0] tb;
        begin
            @(negedge clk);
            a = ta; b = tb; start = 1;
            @(posedge clk);
            @(negedge clk);
            start = 0;
            if (done) begin
                $display("DIVFP %0d %0d %0d %0d %0d", ta, tb, val, dbz, ovf);
            end else begin
                while (!done) begin
                    @(posedge clk);
                    @(negedge clk);
                end
                $display("DIVFP %0d %0d %0d %0d %0d", ta, tb, val, dbz, ovf);
            end
        end
    endtask

    initial begin
        rst = 1; start = 0; a = 0; b = 0;
        repeat(3) @(posedge clk);
        @(negedge clk);
        rst = 0;
{calls}
        #100;
        $finish;
    end
endmodule
"""


# ============================================================================
# Simulation
# ============================================================================

def simulate(tb_path, sv_files, output_name):
    """Compile with iverilog and simulate with vvp, return output lines."""
    sv_str = " ".join(sv_files)
    vvp_path = f"/app/{output_name}.vvp"
    compile_cmd = f"iverilog -g2012 -o {vvp_path} {tb_path} {sv_str}"
    run_cmd(compile_cmd)
    sim_output = run_cmd(f"vvp {vvp_path}")
    return [line for line in sim_output.strip().split("\n") if line.strip()]


# ============================================================================
# Parse simulation output
# ============================================================================

def parse_div(lines):
    results = []
    for line in lines:
        if not line.startswith("DIV "):
            continue
        parts = line.split()
        a, b = int(parts[1]), int(parts[2])
        val, rem, dbz = int(parts[3]), int(parts[4]), int(parts[5])
        if dbz:
            results.append({"a": a, "b": b, "quotient": 0, "remainder": 0, "dbz": True})
        else:
            results.append({"a": a, "b": b, "quotient": val, "remainder": rem, "dbz": False})
    return results


def parse_sqrt(lines):
    results = []
    for line in lines:
        if not line.startswith("SQRT "):
            continue
        parts = line.split()
        rad, root, rem = int(parts[1]), int(parts[2]), int(parts[3])
        results.append({"radicand": rad, "root": root, "remainder": rem})
    return results


def parse_divfp(lines):
    results = []
    for line in lines:
        if not line.startswith("DIVFP "):
            continue
        parts = line.split()
        a, b = int(parts[1]), int(parts[2])
        val, dbz, ovf = int(parts[3]), int(parts[4]), int(parts[5])
        results.append({
            "a": a, "b": b, "quotient": val,
            "dbz": dbz == 1, "ovf": ovf == 1,
        })
    return results


# ============================================================================
# Q4.21 signed fixed-point Mandelbrot
# ============================================================================

FP_WIDTH = 25
FP_FBITS = 21
FP_MASK = (1 << FP_WIDTH) - 1
FP_FOUR = 4 << FP_FBITS  # 8388608


def fp_to_signed(v):
    v = v & FP_MASK
    if v >= (1 << (FP_WIDTH - 1)):
        return v - (1 << FP_WIDTH)
    return v


def fp_mul(a, b):
    sa = fp_to_signed(a)
    sb = fp_to_signed(b)
    product = sa * sb
    return (product >> FP_FBITS) & FP_MASK


def mandelbrot(cx, cy, max_iter=255):
    x, y, x2, y2 = 0, 0, 0, 0
    for iteration in range(max_iter):
        sum_sq = (x2 + y2) & FP_MASK
        if fp_to_signed(sum_sq) > fp_to_signed(FP_FOUR):
            return iteration
        xy = fp_mul(x, y)
        two_xy = (xy << 1) & FP_MASK
        y_new = (two_xy + cy) & FP_MASK
        x_new = (x2 - y2 + cx) & FP_MASK
        x = x_new & FP_MASK
        y = y_new & FP_MASK
        x2 = fp_mul(x, x)
        y2 = fp_mul(y, y)
    return max_iter


# ============================================================================
# Main
# ============================================================================

def main():
    os.makedirs("/app", exist_ok=True)

    # Write testbenches
    write_file("/app/tb_divu_int.v", gen_tb_divu_int())
    write_file("/app/tb_sqrt_int.v", gen_tb_sqrt_int())
    write_file("/app/tb_divu_fp.v", gen_tb_divu())

    # Simulate arithmetic modules
    print("Simulating divu_int...")
    div_lines = simulate(
        "/app/tb_divu_int.v", ["/app/verilog/divu_int.sv"], "sim_divu_int"
    )
    div_results = parse_div(div_lines)
    print(f"  Got {len(div_results)} division results")

    print("Simulating sqrt_int...")
    sqrt_lines = simulate(
        "/app/tb_sqrt_int.v", ["/app/verilog/sqrt_int.sv"], "sim_sqrt_int"
    )
    sqrt_results = parse_sqrt(sqrt_lines)
    print(f"  Got {len(sqrt_results)} sqrt results")

    print("Simulating divu (fixed-point)...")
    divfp_lines = simulate(
        "/app/tb_divu_fp.v", ["/app/verilog/divu.sv"], "sim_divu_fp"
    )
    divfp_results = parse_divfp(divfp_lines)
    print(f"  Got {len(divfp_results)} fp division results")

    # Compute Mandelbrot grid
    print("Computing Mandelbrot grid...")
    x_reals = [-2.0, -1.75, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5]
    y_reals = [-1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
    grid = []
    for cx_real in x_reals:
        cx_fp = int(cx_real * (1 << FP_FBITS))
        cx_masked = cx_fp & FP_MASK
        for cy_real in y_reals:
            cy_fp = int(cy_real * (1 << FP_FBITS))
            cy_masked = cy_fp & FP_MASK
            iters = mandelbrot(cx_masked, cy_masked)
            grid.append({"cx": cx_fp, "cy": cy_fp, "iterations": iters})
    print(f"  Computed {len(grid)} grid points")

    # Assemble results
    results = {
        "divu_int": {"width": 32, "results": div_results},
        "sqrt_int": {"width": 32, "results": sqrt_results},
        "divu_fp": {"width": 25, "fbits": 21, "results": divfp_results},
        "mandelbrot": {
            "width": FP_WIDTH,
            "fbits": FP_FBITS,
            "max_iter": 255,
            "grid": grid,
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Done. Wrote /app/results.json")


if __name__ == "__main__":
    main()
