// Testbench for CORX multiplication engine
// Exercises 0xFFFF * 0xF00F and dumps VCD waveform

`timescale 1ns/1ps

module corx_tb;
    reg         clk;
    reg         rst_n;
    reg         start;
    reg  [15:0] multiplier;
    reg  [15:0] multiplicand;
    wire [15:0] result_high;
    wire [15:0] result_low;
    wire        done;

    corx dut (
        .clk          (clk),
        .rst_n        (rst_n),
        .start        (start),
        .multiplier   (multiplier),
        .multiplicand (multiplicand),
        .result_high  (result_high),
        .result_low   (result_low),
        .done         (done)
    );

    // 10 ns period clock (100 MHz)
    initial clk = 0;
    always #5 clk = ~clk;

    // VCD waveform dump — all signals including DUT internals
    initial begin
        $dumpfile("/app/corx_sim.vcd");
        $dumpvars(0, corx_tb);
    end

    // Main stimulus
    initial begin
        // Initialise inputs
        rst_n        = 0;
        start        = 0;
        multiplier   = 16'hFFFF;
        multiplicand = 16'hF00F;

        // Hold reset for 3 rising edges
        repeat (3) @(posedge clk);
        @(negedge clk);
        rst_n = 1;

        // Wait two full cycles after reset release
        repeat (2) @(posedge clk);

        // Assert start on a falling edge so it is stable at the next rising edge
        @(negedge clk);
        start = 1;
        @(negedge clk);
        start = 0;

        // Wait for the done flag
        wait (done == 1'b1);
        repeat (2) @(posedge clk);

        $display("VERILOG RESULT: DX=0x%04h AX=0x%04h", result_high, result_low);
        $finish;
    end

    // Safety timeout
    initial begin
        #50000;
        $display("TIMEOUT: simulation did not finish");
        $finish;
    end
endmodule
