//
// fp8_adder_tb.v - Testbench for the FP8 E4M3 adder module.
// Outputs results as "R <a> <b> <rounding> <result>" lines on stdout.

`timescale 1ns/1ps

module fp8_adder_tb;

reg [7:0] a, b;
reg [2:0] rounding;
wire [7:0] result;

fp8_adder uut (
    .a(a),
    .b(b),
    .rounding(rounding),
    .result(result)
);

task run_test(input [7:0] ta, input [7:0] tb, input [2:0] tr);
    begin
        a = ta;
        b = tb;
        rounding = tr;
        #10;
        $display("R %0d %0d %0d %0d", ta, tb, tr, result);
    end
endtask

initial begin
    // Basic addition
    run_test(8'h38, 8'h38, 3'd0);  // 1+1=2
    run_test(8'h38, 8'h30, 3'd0);  // 1+0.5=1.5
    run_test(8'h40, 8'hB8, 3'd0);  // 2+(-1)=1
    run_test(8'hB8, 8'hB8, 3'd0);  // -1+(-1)=-2

    // Subnormal addition
    run_test(8'h01, 8'h01, 3'd0);  // sub+sub
    run_test(8'h07, 8'h01, 3'd0);  // sub->normal boundary

    // Special values
    run_test(8'h79, 8'h38, 3'd0);  // NaN + 1 = NaN
    run_test(8'h78, 8'h38, 3'd0);  // Inf + 1 = Inf
    run_test(8'h78, 8'hF8, 3'd0);  // Inf + (-Inf) = NaN
    run_test(8'h78, 8'h78, 3'd0);  // Inf + Inf = Inf

    // Signed zeros
    run_test(8'h00, 8'h80, 3'd0);  // +0+(-0)=+0 RNE
    run_test(8'h00, 8'h80, 3'd3);  // +0+(-0)=-0 RD
    run_test(8'h3C, 8'hBC, 3'd0);  // 1.5+(-1.5)=+0
    run_test(8'h3C, 8'hBC, 3'd3);  // 1.5+(-1.5)=-0 RD

    // Overflow with rounding modes
    run_test(8'h77, 8'h58, 3'd0);  // overflow RNE -> Inf
    run_test(8'h77, 8'h58, 3'd4);  // overflow RZ -> max
    run_test(8'h77, 8'h58, 3'd3);  // overflow RD pos -> max
    run_test(8'h77, 8'h58, 3'd2);  // overflow RU pos -> Inf

    // Tie-breaking
    run_test(8'h38, 8'h18, 3'd0);  // tie RNE even->down
    run_test(8'h39, 8'h18, 3'd0);  // tie RNE odd->up
    run_test(8'h38, 8'h18, 3'd1);  // tie RNA->away

    $finish;
end

endmodule
