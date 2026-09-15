`timescale 1ns/1ps
// Ring oscillator verification testbench

module verify_ring_osc;
    reg  enable;
    wire osc_out;

    ring_oscillator #(.NUM_INV(31)) dut (.enable(enable), .osc_out(osc_out));

    integer transitions;
    reg     prev;

    initial begin
        enable = 0;
        transitions = 0;
        #200;

        enable = 1;
        #10;
        prev = osc_out;

        repeat (100000) begin
            #1;
            if (osc_out !== prev && osc_out !== 1'bx) begin
                transitions = transitions + 1;
                prev = osc_out;
            end
        end

        if (transitions > 100)
            $display("RESULT: PASS (%0d transitions)", transitions);
        else
            $display("RESULT: FAIL (%0d transitions)", transitions);
        $finish;
    end
endmodule
