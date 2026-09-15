`timescale 1ns/1ps
// Basic adder testbench for debugging

module tb_adder;
    reg  [7:0] a, b;
    reg        cin;
    wire [7:0] sum;
    wire       cout;

`ifdef TEST_RIPPLE
    ripple_carry_adder #(.WIDTH(8)) dut (.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout));
`endif
`ifdef TEST_KOGGE
    kogge_stone_adder #(.WIDTH(8)) dut (.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout));
`endif
`ifdef TEST_BRENT
    brent_kung_adder #(.WIDTH(8)) dut (.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout));
`endif
`ifdef TEST_SKLANSKY
    sklansky_adder #(.WIDTH(8)) dut (.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout));
`endif

    integer i, errors;
    reg [8:0] expected;

    initial begin
        $dumpfile("adder.vcd");
        $dumpvars(0, tb_adder);
        errors = 0;

        for (i = 0; i < 10000; i = i + 1) begin
            a   = $random;
            b   = $random;
            cin = $random & 1;
            #10;
            expected = a + b + cin;
            if ({cout, sum} !== expected[8:0]) begin
                errors = errors + 1;
                if (errors <= 10)
                    $display("MISMATCH: a=0x%02h b=0x%02h cin=%0b => got 0x%03h expected 0x%03h",
                             a, b, cin, {cout, sum}, expected[8:0]);
            end
        end

        if (errors == 0)
            $display("TEST PASSED: 10000 random vectors");
        else
            $display("TEST FAILED: %0d errors in 10000 vectors", errors);
        $finish;
    end
endmodule
