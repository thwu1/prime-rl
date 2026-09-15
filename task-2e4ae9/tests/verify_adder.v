`timescale 1ns/1ps
// Exhaustive adder verification testbench

module verify_adder;
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
        errors = 0;

        // Exhaustive test: all 256*256 input pairs with cin=0
        for (i = 0; i < 65536; i = i + 1) begin
            a = i / 256;
            b = i % 256;
            cin = 0;
            #10;
            expected = a + b;
            if ({cout, sum} !== expected[8:0]) begin
                errors = errors + 1;
                if (errors <= 5)
                    $display("MISMATCH cin=0: a=0x%02h b=0x%02h got=0x%03h exp=0x%03h",
                             a, b, {cout, sum}, expected[8:0]);
            end
        end

        // Exhaustive test: all 256*256 input pairs with cin=1
        for (i = 0; i < 65536; i = i + 1) begin
            a = i / 256;
            b = i % 256;
            cin = 1;
            #10;
            expected = a + b + 1;
            if ({cout, sum} !== expected[8:0]) begin
                errors = errors + 1;
                if (errors <= 5)
                    $display("MISMATCH cin=1: a=0x%02h b=0x%02h got=0x%03h exp=0x%03h",
                             a, b, {cout, sum}, expected[8:0]);
            end
        end

        if (errors == 0)
            $display("RESULT: PASS");
        else
            $display("RESULT: FAIL (%0d errors)", errors);
        $finish;
    end
endmodule
