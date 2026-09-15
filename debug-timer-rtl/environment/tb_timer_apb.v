`timescale 1ns / 1ps
//
// Testbench for dual-channel timer with APB-Lite interface
//
module tb_timer_apb;

    reg         pclk;
    reg         presetn;
    reg  [7:0]  paddr;
    reg         psel;
    reg         penable;
    reg         pwrite;
    reg  [31:0] pwdata;
    wire [31:0] prdata;
    wire        pready;
    wire        irq;
    reg         capture_in_0;
    reg         capture_in_1;

    timer_apb uut (
        .pclk        (pclk),
        .presetn     (presetn),
        .paddr       (paddr),
        .psel        (psel),
        .penable     (penable),
        .pwrite      (pwrite),
        .pwdata      (pwdata),
        .prdata      (prdata),
        .pready      (pready),
        .irq         (irq),
        .capture_in_0(capture_in_0),
        .capture_in_1(capture_in_1)
    );

    // 10 ns clock period (100 MHz)
    initial pclk = 0;
    always #5 pclk = ~pclk;

    // ---- APB helper tasks ----
    task apb_write;
        input [7:0]  addr;
        input [31:0] data;
        begin
            @(posedge pclk);
            paddr   <= addr;
            psel    <= 1'b1;
            penable <= 1'b0;
            pwrite  <= 1'b1;
            pwdata  <= data;
            @(posedge pclk);
            penable <= 1'b1;
            @(posedge pclk);
            psel    <= 1'b0;
            penable <= 1'b0;
            pwrite  <= 1'b0;
        end
    endtask

    task apb_read;
        input  [7:0]  addr;
        output [31:0] data;
        begin
            @(posedge pclk);
            paddr   <= addr;
            psel    <= 1'b1;
            penable <= 1'b0;
            pwrite  <= 1'b0;
            @(posedge pclk);
            penable <= 1'b1;
            @(posedge pclk);
            data = prdata;
            psel    <= 1'b0;
            penable <= 1'b0;
        end
    endtask

    integer pass_count;
    integer fail_count;
    reg [31:0] rd;

    initial begin
        $dumpfile("timer_sim.vcd");
        $dumpvars(0, tb_timer_apb);

        pass_count = 0;
        fail_count = 0;

        // ---- Reset ----
        presetn      = 0;
        psel         = 0;
        penable      = 0;
        pwrite       = 0;
        paddr        = 0;
        pwdata       = 0;
        capture_in_0 = 0;
        capture_in_1 = 0;
        repeat (5) @(posedge pclk);
        presetn = 1;
        repeat (3) @(posedge pclk);

        // ===========================================================
        // TEST 1 — Channel counter register isolation
        // ===========================================================
        $display("TEST 1: Channel counter register isolation");

        apb_write(8'h00, 32'h0);           // global off
        apb_write(8'h10, 32'h0);           // ch0 disabled
        apb_write(8'h20, 32'h0);           // ch1 disabled
        apb_write(8'h14, 32'hDEAD_BEEF);   // CH0_CNT
        apb_write(8'h24, 32'h1234_5678);   // CH1_CNT

        apb_read(8'h14, rd);
        if (rd == 32'hDEADBEEF) begin
            $display("  [PASS] CH0_CNT readback = 0x%08h", rd);
            pass_count = pass_count + 1;
        end else begin
            $display("  [FAIL] CH0_CNT readback: expected 0xDEADBEEF, got 0x%08h", rd);
            fail_count = fail_count + 1;
        end

        apb_read(8'h24, rd);
        if (rd == 32'h12345678) begin
            $display("  [PASS] CH1_CNT readback = 0x%08h", rd);
            pass_count = pass_count + 1;
        end else begin
            $display("  [FAIL] CH1_CNT readback: expected 0x12345678, got 0x%08h", rd);
            fail_count = fail_count + 1;
        end

        // ===========================================================
        // TEST 2 — Prescaler divide-by-1 (prescaler_div = 0)
        // ===========================================================
        $display("TEST 2: Prescaler divide-by-1");

        apb_write(8'h00, 32'h0);           // disable
        apb_write(8'h10, 32'h0000_0001);   // ch0 enable, no auto-reload
        apb_write(8'h18, 32'h0);           // ch0 cmp = 0 (free-running)
        apb_write(8'h14, 32'h0);           // ch0 cnt = 0
        apb_write(8'h20, 32'h0);           // ch1 disabled
        apb_write(8'h24, 32'h0);           // ch1 cnt = 0

        apb_write(8'h00, 32'h0000_0001);   // global en, prescaler_div = 0
        repeat (60) @(posedge pclk);
        apb_write(8'h00, 32'h0);           // disable

        apb_read(8'h14, rd);
        // prescaler_div=0 -> divide-by-1 -> tick every cycle
        // After ~60 clocks, counter should be ~55-58
        if (rd >= 32'd40) begin
            $display("  [PASS] CH0_CNT = %0d (>= 40 for div-by-1)", rd);
            pass_count = pass_count + 1;
        end else begin
            $display("  [FAIL] CH0_CNT = %0d (expected >= 40 for div-by-1)", rd);
            fail_count = fail_count + 1;
        end

        // ===========================================================
        // TEST 3 — Compare match with auto-reload resets counter to 0
        // ===========================================================
        $display("TEST 3: Compare match with auto-reload");

        apb_write(8'h00, 32'h0);           // disable
        apb_write(8'h10, 32'h0000_0003);   // ch0: enable + auto-reload
        apb_write(8'h18, 32'h0000_000A);   // ch0 cmp = 10
        apb_write(8'h14, 32'h0);           // ch0 cnt = 0

        apb_write(8'h00, 32'h0000_0001);   // enable, prescaler_div = 0
        repeat (200) @(posedge pclk);
        apb_write(8'h00, 32'h0);           // disable

        apb_read(8'h14, rd);
        // Counter cycles 0..10,0..10,... — stopped value should be < 10
        // If auto-reload resets to cmp instead of 0, counter sticks at 10
        if (rd < 32'd10) begin
            $display("  [PASS] CH0_CNT = %0d (< 10, auto-reload to 0 works)", rd);
            pass_count = pass_count + 1;
        end else begin
            $display("  [FAIL] CH0_CNT = %0d (expected < 10, auto-reload may be wrong)", rd);
            fail_count = fail_count + 1;
        end

        // Verify compare-match interrupt flag was set
        apb_read(8'h08, rd);
        if (rd[0] == 1'b1) begin
            $display("  [PASS] INT_FLAG[0] (ch0 compare match) is set");
            pass_count = pass_count + 1;
        end else begin
            $display("  [FAIL] INT_FLAG[0] not set after compare match: 0x%08h", rd);
            fail_count = fail_count + 1;
        end

        // ===========================================================
        // TEST 4 — Interrupt flag write-1-to-clear
        // ===========================================================
        $display("TEST 4: Interrupt flag write-1-to-clear");

        apb_read(8'h08, rd);
        if (rd[0] != 1'b1) begin
            $display("  [FAIL] INT_FLAG[0] not set — cannot test W1C");
            fail_count = fail_count + 1;
        end else begin
            apb_write(8'h08, 32'h0000_0001);   // W1C: write 1 to bit 0
            repeat (3) @(posedge pclk);
            apb_read(8'h08, rd);
            if (rd[0] == 1'b0) begin
                $display("  [PASS] INT_FLAG[0] cleared by W1C");
                pass_count = pass_count + 1;
            end else begin
                $display("  [FAIL] INT_FLAG[0] still set after W1C: 0x%08h", rd);
                fail_count = fail_count + 1;
            end
        end

        // ===========================================================
        // TEST 5 — Capture on rising edge (channel 0)
        // ===========================================================
        $display("TEST 5: Capture on rising edge (ch0)");

        apb_write(8'h00, 32'h0);           // disable
        // ch0: enable + capture_en, edge=0 (rising)
        apb_write(8'h10, 32'h0000_0005);   // [0]=en [2]=cap_en [3]=0
        apb_write(8'h18, 32'h0);           // cmp=0 (free-running)
        apb_write(8'h14, 32'h0);           // cnt=0

        apb_write(8'h00, 32'h0000_0001);   // enable, prescaler_div=0

        // Let counter run
        repeat (30) @(posedge pclk);

        // Generate rising edge
        capture_in_0 = 1'b0;
        repeat (4) @(posedge pclk);        // hold low
        capture_in_0 = 1'b1;               // 0->1 rising edge
        repeat (6) @(posedge pclk);        // wait for synchronizer

        apb_write(8'h00, 32'h0);           // disable

        apb_read(8'h1C, rd);               // read CH0_CAP
        if (rd > 32'd0) begin
            $display("  [PASS] CH0_CAP = %0d (captured on rising edge)", rd);
            pass_count = pass_count + 1;
        end else begin
            $display("  [FAIL] CH0_CAP = %0d (expected > 0 — capture may use wrong edge)", rd);
            fail_count = fail_count + 1;
        end

        // ===========================================================
        // TEST 6 — Prescaler divide-by-2 (prescaler_div = 1)
        // ===========================================================
        $display("TEST 6: Prescaler divide-by-2");

        capture_in_0 = 1'b0;
        apb_write(8'h00, 32'h0);           // disable
        apb_write(8'h10, 32'h0000_0001);   // ch0 enable
        apb_write(8'h18, 32'h0);           // cmp=0 (free-running)
        apb_write(8'h14, 32'h0);           // cnt=0
        apb_write(8'h20, 32'h0);           // ch1 disabled

        apb_write(8'h00, 32'h0000_0101);   // prescaler_div=1, en=1
        repeat (200) @(posedge pclk);
        apb_write(8'h00, 32'h0);           // disable

        apb_read(8'h14, rd);
        // Correct div-by-2: ~95-100 ticks in 200 clocks
        // Buggy div-by-3:  ~63-66 ticks
        if (rd >= 32'd80) begin
            $display("  [PASS] CH0_CNT = %0d (>= 80 for div-by-2)", rd);
            pass_count = pass_count + 1;
        end else begin
            $display("  [FAIL] CH0_CNT = %0d (expected >= 80 for div-by-2)", rd);
            fail_count = fail_count + 1;
        end

        // ===========================================================
        // Summary
        // ===========================================================
        $display("");
        $display("========================================");
        $display("RESULTS: %0d passed, %0d failed out of %0d checks",
                 pass_count, fail_count, pass_count + fail_count);
        if (fail_count == 0)
            $display("ALL TESTS PASSED");
        else
            $display("SOME TESTS FAILED");
        $display("========================================");
        $finish;
    end

    // Watchdog
    initial begin
        #200000;
        $display("TIMEOUT: simulation exceeded time limit");
        $display("SOME TESTS FAILED");
        $finish;
    end

endmodule
