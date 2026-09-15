localparam test_period = 5;

`ifndef TB_NO_CLOCK
task pulse_clock;
    begin
        clock = 1'b1;
        #test_period;
        clock = 1'b0;
        #test_period;
    end
endtask
`endif

`define assert(cond, msg) \
    if (!(cond)) begin \
        $display("ASSERTION FAILED: %s", msg); \
        $fatal; \
    end
