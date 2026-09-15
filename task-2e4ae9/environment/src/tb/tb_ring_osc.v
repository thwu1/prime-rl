`timescale 1ns/1ps
// Ring oscillator testbench

module tb_ring_osc;
    reg  enable;
    wire osc_out;

    ring_oscillator dut (.enable(enable), .osc_out(osc_out));

    integer count;
    reg     prev;

    initial begin
        $dumpfile("ring_osc.vcd");
        $dumpvars(0, tb_ring_osc);

        enable = 0;
        count  = 0;
        #200;

        enable = 1;
        #10;
        prev = osc_out;

        repeat (5000) begin
            #1;
            if (osc_out !== prev && osc_out !== 1'bx) begin
                count = count + 1;
                prev  = osc_out;
            end
        end

        $display("Oscillator transitions: %0d", count);
        if (count > 10)
            $display("Ring oscillator: WORKING");
        else
            $display("Ring oscillator: NOT OSCILLATING — check inversion count in feedback path");
        $finish;
    end
endmodule
