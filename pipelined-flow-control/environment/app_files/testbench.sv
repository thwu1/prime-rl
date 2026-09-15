
//============================================================================
// Self-checking testbench for the pipelined compute module.
//
// Formula under test:  result = isqrt(a*a + b*b) + a*b - c
// All arithmetic is unsigned 32-bit.
//
// Verification strategy:
//   - A queue holds expected results (pushed on input handshake,
//     popped / compared on output handshake).
//   - Tests cover directed values, back-to-back streaming,
//     backpressure, and random stimuli with random backpressure.
//============================================================================

module testbench;

    //------------------------------------------------------------------------
    // Signals
    //------------------------------------------------------------------------

    reg          clk;
    reg          rst;

    reg          arg_vld;
    wire         arg_rdy;

    reg  [31:0]  a;
    reg  [31:0]  b;
    reg  [31:0]  c;

    wire         res_vld;
    reg          res_rdy;

    wire [31:0]  res;

    //------------------------------------------------------------------------
    // DUT instantiation
    //------------------------------------------------------------------------

    compute dut (.*);

    //------------------------------------------------------------------------
    // Clock: 100 MHz (period 10 time-units)
    //------------------------------------------------------------------------

    initial begin
        clk = 1'b1;
        forever #5 clk = ~clk;
    end

    //------------------------------------------------------------------------
    // Reset
    //------------------------------------------------------------------------

    task reset;
        begin
            rst <= 1'bx;
            repeat (3) @(posedge clk);
            rst <= 1'b1;
            repeat (3) @(posedge clk);
            rst <= 1'b0;
        end
    endtask

    //------------------------------------------------------------------------
    // Integer square root (must match pipe_isqrt behaviour exactly)
    //------------------------------------------------------------------------

    function [31:0] isqrt_func;
        input [31:0] val;
        reg [31:0] r;
        reg [31:0] bm;
        begin
            r  = 32'd0;
            bm = 32'h40000000;         // 1 << 30

            while (bm != 0 && bm > val)
                bm = bm >> 2;

            while (bm != 0) begin
                if (val >= r + bm) begin
                    val = val - r - bm;
                    r   = (r >> 1) + bm;
                end else begin
                    r = r >> 1;
                end
                bm = bm >> 2;
            end

            isqrt_func = r;
        end
    endfunction

    //------------------------------------------------------------------------
    // Expected-result computation
    //------------------------------------------------------------------------

    function [31:0] compute_expected;
        input [31:0] va, vb, vc;
        reg [31:0] aa, bb, ab, s, sq;
        begin
            aa = va * va;
            bb = vb * vb;
            ab = va * vb;
            s  = aa + bb;
            sq = isqrt_func(s);
            compute_expected = sq + ab - vc;
        end
    endfunction

    //------------------------------------------------------------------------
    // Stimulus utilities
    //------------------------------------------------------------------------

    localparam MAX_LATENCY       = 30;
    localparam GAP_BETWEEN_TESTS = 100;
    localparam MANY_CYCLES       = 300;
    localparam TIMEOUT           = 100000;

    string test_id;
    initial $sformat(test_id, "%s", `__FILE__);

    function integer randomize_gap;
        integer gc;
        begin
            gc = $urandom_range(1, 100);
            if      (gc <= 60) randomize_gap = 0;
            else if (gc <= 95) randomize_gap = $urandom_range(1, 3);
            else               randomize_gap = $urandom_range(4, MAX_LATENCY + 2);
        end
    endfunction

    task drive_arg_vld;
        input integer random_gap;
        input integer gap;
        begin
            arg_vld <= 1'b1;
            @(posedge clk);

            while (!arg_rdy)
                @(posedge clk);

            arg_vld <= 1'b0;

            if (random_gap)
                gap = randomize_gap();

            repeat (gap) @(posedge clk);
        end
    endtask

    task make_gap;
        begin
            repeat (MAX_LATENCY + GAP_BETWEEN_TESTS) @(posedge clk);
        end
    endtask

    //------------------------------------------------------------------------
    // Main stimulus
    //------------------------------------------------------------------------

    task run;
        integer i;
        begin
            $display("--------------------------------------------------");
            $display("Running %s", test_id);

            arg_vld <= 1'b0;
            res_rdy <= 1'b1;
            reset();

            // ---- Phase 1: idle check ----
            $display("********** Idle check");
            if (arg_rdy !== 1'b1) begin
                $display("FAIL %s: arg_rdy must be 1 when idle, got %b",
                         test_id, arg_rdy);
                fail_reported = 1;
                $finish;
            end

            // ---- Phase 2: single directed test ----
            $display("********** Single directed test");
            a <= 32'd3;  b <= 32'd4;  c <= 32'd1;
            drive_arg_vld(0, 0);
            make_gap();

            // ---- Phase 3: directed tests with varying gaps ----
            $display("********** Directed tests with gaps");
            for (i = 0; i < 20; i = i + 1) begin
                a <= i * 7 + 3;
                b <= i * 11 + 5;
                c <= i * 13 + 7;
                drive_arg_vld(0, i % 5);
            end
            make_gap();

            // ---- Phase 4: back-to-back (constrained random) ----
            $display("********** Back-to-back constrained random");
            for (i = 0; i < 200; i = i + 1) begin
                a <= $urandom_range(0, 1000);
                b <= $urandom_range(0, 1000);
                c <= $urandom_range(0, 1000);
                drive_arg_vld(0, 0);
            end
            make_gap();

            // ---- Phase 5: continuous fill, then backpressure ----
            $display("********** Fill pipeline");

            if (arg_rdy !== 1'b1) begin
                $display("FAIL %s: arg_rdy must be 1 before fill, got %b",
                         test_id, arg_rdy);
                fail_reported = 1;
                $finish;
            end

            arg_vld <= 1'b1;
            for (i = 0; i < MANY_CYCLES; i = i + 1) begin
                if (arg_rdy) begin
                    a <= i;
                    b <= i + 1;
                    c <= i + 2;
                end
                @(posedge clk);
            end

            $display("********** Applying backpressure");
            res_rdy <= 1'b0;

            for (i = MANY_CYCLES; i < 2 * MANY_CYCLES; i = i + 1) begin
                if (arg_rdy) begin
                    a <= i;
                    b <= i + 1;
                    c <= i + 2;
                end
                @(posedge clk);
            end

            $display("********** Draining pipeline");
            arg_vld <= 1'b0;
            res_rdy <= 1'b1;
            repeat (MANY_CYCLES) @(posedge clk);
            make_gap();

            // ---- Phase 6: random with random backpressure ----
            $display("********** Random with random backpressure");

            fork
                repeat (MANY_CYCLES) begin
                    a <= $urandom;
                    b <= $urandom;
                    c <= $urandom;
                    drive_arg_vld(1, 0);
                end

                repeat (MANY_CYCLES * 10) begin
                    res_rdy <= $urandom;
                    @(posedge clk);
                end
            join_any

            res_rdy <= 1'b1;
            make_gap();
        end
    endtask

    //------------------------------------------------------------------------
    // Top-level control
    //------------------------------------------------------------------------

    initial begin
        `ifdef __ICARUS__
            $dumpvars;
        `endif
        run();
        $finish;
    end

    //------------------------------------------------------------------------
    // Checker — queue-based scoreboard
    //------------------------------------------------------------------------

    reg [31:0] queue [$];
    reg [31:0] expected;

    reg was_reset     = 0;
    reg fail_reported = 0;

    always @(posedge clk) begin
        if (rst) begin
            queue     = {};
            was_reset = 1;
        end else if (was_reset) begin

            // Connectivity / X checks
            if (arg_rdy === 1'bz) begin
                $display("FAIL %s: arg_rdy not connected (Z)", test_id);
                fail_reported = 1;  $finish;
            end
            if (arg_rdy === 1'bx) begin
                $display("FAIL %s: arg_rdy undefined (X)", test_id);
                fail_reported = 1;  $finish;
            end
            if (res_vld === 1'bz) begin
                $display("FAIL %s: res_vld not connected (Z)", test_id);
                fail_reported = 1;  $finish;
            end
            if (res_vld === 1'bx) begin
                $display("FAIL %s: res_vld undefined (X)", test_id);
                fail_reported = 1;  $finish;
            end

            // Push on input handshake
            if (arg_vld & arg_rdy)
                queue.push_back(compute_expected(a, b, c));

            // Pop / compare on output handshake
            if (res_vld & res_rdy) begin
                if (queue.size() == 0) begin
                    $display("FAIL %s: unexpected result %h", test_id, res);
                    fail_reported = 1;  $finish;
                end else begin
                    `ifdef __ICARUS__
                        expected = queue[0];
                        queue.delete(0);
                    `else
                        expected = queue.pop_front();
                    `endif

                    if (res !== expected) begin
                        $display("FAIL %s: mismatch exp=%h got=%h",
                                 test_id, expected, res);
                        fail_reported = 1;  $finish;
                    end
                end
            end
        end
    end

    //------------------------------------------------------------------------
    // Performance counters
    //------------------------------------------------------------------------

    reg [31:0] n_cycles = 0;
    reg [31:0] arg_cnt  = 0;
    reg [31:0] res_cnt  = 0;

    always @(posedge clk) begin
        if (rst) begin
            n_cycles <= 0;
            arg_cnt  <= 0;
            res_cnt  <= 0;
        end else begin
            n_cycles <= n_cycles + 1;
            if (arg_vld & arg_rdy) arg_cnt <= arg_cnt + 1;
            if (res_vld & res_rdy) res_cnt <= res_cnt + 1;
        end
    end

    //------------------------------------------------------------------------
    // Final verdict
    //------------------------------------------------------------------------

    final begin
        $display("\n\nnumber of transfers: arg %0d  res %0d  per %0d cycles",
                 arg_cnt, res_cnt, n_cycles);

        if (arg_cnt == 0)
            $display("FAIL %s: arg_cnt == 0", test_id);
        else if (res_cnt == 0)
            $display("FAIL %s: res_cnt == 0", test_id);
        else if (arg_cnt != res_cnt)
            $display("FAIL %s: arg_cnt (%0d) != res_cnt (%0d)",
                     test_id, arg_cnt, res_cnt);
        else if (fail_reported)
            ;  // already reported
        else if (queue.size() == 0)
            $display("PASS %s", test_id);
        else begin
            $display("FAIL %s: %0d results left in queue", test_id, queue.size());
        end
    end

    //------------------------------------------------------------------------
    // Timeout watchdog
    //------------------------------------------------------------------------

    initial begin
        repeat (TIMEOUT) @(posedge clk);
        $display("FAIL %s: timeout after %0d cycles!", test_id, TIMEOUT);
        fail_reported = 1;
        $finish;
    end

endmodule
