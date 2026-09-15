/* Testbench for verifying gate-level netlist against RTL */
/* Verifies 4-bit pipelined adder functional correctness */

`timescale 1ns/1ps

module testbench;
    reg clk, rst_n;
    reg [3:0] a, b;
    wire [3:0] sum;
    wire cout;

    adder_pipe dut (
        .clk(clk), .rst_n(rst_n),
        .a(a), .b(b),
        .sum(sum), .cout(cout)
    );

    initial clk = 0;
    always #5 clk = ~clk;

    integer errors = 0;
    integer tests = 0;
    reg [3:0] a_pipe [0:1];
    reg [3:0] b_pipe [0:1];
    reg pipe_valid;
    integer pipe_count;
    reg [4:0] expected;

    initial begin
        rst_n = 0;
        a = 0; b = 0;
        pipe_count = 0;
        pipe_valid = 0;
        #25;
        rst_n = 1;

        /* Exhaustive test: all 256 input combinations */
        repeat(256) begin
            @(negedge clk);
            /* Shift pipeline tracker */
            a_pipe[1] = a_pipe[0];
            b_pipe[1] = b_pipe[0];
            a_pipe[0] = a;
            b_pipe[0] = b;

            if (pipe_count >= 2) begin
                expected = a_pipe[1] + b_pipe[1];
                if ({cout, sum} !== expected) begin
                    $display("FAIL: a=%0d b=%0d => sum=%0d cout=%0d, expected %0d",
                             a_pipe[1], b_pipe[1], sum, cout, expected);
                    errors = errors + 1;
                end
                tests = tests + 1;
            end
            pipe_count = pipe_count + 1;

            /* Advance inputs */
            {a, b} = {a, b} + 1;
        end

        /* Flush pipeline */
        repeat(3) begin
            @(negedge clk);
            a_pipe[1] = a_pipe[0];
            b_pipe[1] = b_pipe[0];
            a_pipe[0] = a;
            b_pipe[0] = b;
            if (pipe_count >= 2) begin
                expected = a_pipe[1] + b_pipe[1];
                if ({cout, sum} !== expected) begin
                    $display("FAIL: a=%0d b=%0d => sum=%0d cout=%0d, expected %0d",
                             a_pipe[1], b_pipe[1], sum, cout, expected);
                    errors = errors + 1;
                end
                tests = tests + 1;
            end
            pipe_count = pipe_count + 1;
        end

        if (errors == 0)
            $display("PASS: %0d tests passed", tests);
        else
            $display("FAIL: %0d errors in %0d tests", errors, tests);
        $finish;
    end
endmodule
