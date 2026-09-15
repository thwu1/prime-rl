// Testbench for flow_control_wrapper
// Tests correctness, backpressure handling, and idle behavior
//

module tb_flow_control;

    //--------------------------------------------------------------
    // Signals
    //--------------------------------------------------------------

    reg         clk;
    reg         rst;

    reg         arg_vld;
    wire        arg_rdy;
    reg  [31:0] a, b, c;

    wire        res_vld;
    reg         res_rdy;
    wire [31:0] result;

    //--------------------------------------------------------------
    // DUT
    //--------------------------------------------------------------

    flow_control_wrapper dut (
        .clk     (clk),
        .rst     (rst),
        .arg_vld (arg_vld),
        .arg_rdy (arg_rdy),
        .a       (a),
        .b       (b),
        .c       (c),
        .res_vld (res_vld),
        .res_rdy (res_rdy),
        .result  (result)
    );

    //--------------------------------------------------------------
    // Clock
    //--------------------------------------------------------------

    initial begin
        clk = 1;
        forever #5 clk = ~clk;
    end

    //--------------------------------------------------------------
    // Reset
    //--------------------------------------------------------------

    task reset_dut();
        begin
            rst <= 1'bx;
            repeat (3) @(posedge clk);
            rst <= 1'b1;
            repeat (5) @(posedge clk);
            rst <= 1'b0;
        end
    endtask

    //--------------------------------------------------------------
    // Reference integer square root (Newton's method)
    //--------------------------------------------------------------

    function [31:0] isqrt_ref;
        input [31:0] n;
        reg [31:0] x, x1;
        integer i;
        begin
            if (n <= 1) begin
                isqrt_ref = n;
            end else begin
                x = n;
                x1 = (x + 1) / 2;
                for (i = 0; i < 36; i = i + 1) begin
                    if (x1 < x) begin
                        x = x1;
                        x1 = (x + n / x) / 2;
                    end
                end
                isqrt_ref = x;
            end
        end
    endfunction

    //--------------------------------------------------------------
    // Parameters
    //--------------------------------------------------------------

    localparam TIMEOUT         = 100000;
    localparam MANY_CYCLES     = 200;
    localparam GAP_BETWEEN     = 150;

    //--------------------------------------------------------------
    // Modeling and checking (single always block, blocking assigns)
    //--------------------------------------------------------------

    reg [31:0] queue [$];
    reg [31:0] exp;

    reg was_reset               = 0;
    bit fail_is_already_reported = 0;

    // verilator lint_off BLKSEQ
    always @(posedge clk) begin
        if (rst) begin
            queue = {};
            was_reset = 1;
        end else if (was_reset) begin
            // Validate control signals are connected
            if (arg_rdy === 1'bz) begin
                $display("FAIL: arg_rdy is high-Z (not connected)");
                fail_is_already_reported = 1;
                $finish;
            end
            if (arg_rdy === 1'bx) begin
                $display("FAIL: arg_rdy is X (uninitialized)");
                fail_is_already_reported = 1;
                $finish;
            end
            if (res_vld === 1'bz) begin
                $display("FAIL: res_vld is high-Z (not connected)");
                fail_is_already_reported = 1;
                $finish;
            end
            if (res_vld === 1'bx) begin
                $display("FAIL: res_vld is X (uninitialized)");
                fail_is_already_reported = 1;
                $finish;
            end

            // Track accepted inputs
            if (arg_vld && arg_rdy) begin
                exp = isqrt_ref(a * a + b * b) + c;
                queue.push_back(exp);
            end

            // Check delivered outputs
            if (res_vld && res_rdy) begin
                if (queue.size() == 0) begin
                    $display("FAIL: unexpected result %0d", result);
                    fail_is_already_reported = 1;
                    $finish;
                end else begin
                    `ifdef __ICARUS__
                        exp = queue[0];
                        queue.delete(0);
                    `else
                        exp = queue.pop_front();
                    `endif

                    if (result !== exp) begin
                        $display("FAIL: expected %0d, got %0d",
                                 exp, result);
                        fail_is_already_reported = 1;
                        $finish;
                    end
                end
            end
        end
    end
    // verilator lint_on BLKSEQ

    //--------------------------------------------------------------
    // Performance counters
    //--------------------------------------------------------------

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
            if (arg_vld && arg_rdy)
                arg_cnt <= arg_cnt + 1;
            if (res_vld && res_rdy)
                res_cnt <= res_cnt + 1;
        end
    end

    //--------------------------------------------------------------
    // Main test sequence
    //--------------------------------------------------------------

    integer i;

    task run();
        begin
            $display("--------------------------------------------------");
            $display("Running flow control wrapper testbench");

            arg_vld <= 0;
            res_rdy <= 1;
            reset_dut();

            //--- Test 1: arg_rdy when idle -------------------------
            $display("*** Test 1: arg_rdy must be 1 when idle");
            if (arg_rdy !== 1'b1) begin
                $display("FAIL: arg_rdy must be 1 when block is idle, got %b",
                         arg_rdy);
                fail_is_already_reported = 1;
                $finish;
            end

            //--- Test 2: Single input ------------------------------
            $display("*** Test 2: single transaction");
            a <= 3; b <= 4; c <= 10;
            arg_vld <= 1;
            @(posedge clk);
            while (!arg_rdy) @(posedge clk);
            arg_vld <= 0;
            repeat (GAP_BETWEEN) @(posedge clk);

            //--- Test 3: Back-to-back, no backpressure -------------
            $display("*** Test 3: back-to-back, no backpressure");
            arg_vld <= 1;
            for (i = 0; i < MANY_CYCLES; i = i + 1) begin
                if (arg_rdy) begin
                    a <= (i + 1) & 32'h0000FFFF;
                    b <= (i + 2) & 32'h0000FFFF;
                    c <= (i + 3) & 32'h0000FFFF;
                end
                @(posedge clk);
            end
            arg_vld <= 0;
            repeat (GAP_BETWEEN) @(posedge clk);

            //--- Test 4: Backpressure ------------------------------
            $display("*** Test 4: backpressure");
            res_rdy <= 0;
            arg_vld <= 1;

            for (i = 0; i < 50; i = i + 1) begin
                if (arg_rdy) begin
                    a <= 100 + i;
                    b <= 200 + i;
                    c <= i;
                end
                @(posedge clk);
            end
            arg_vld <= 0;

            // Hold backpressure
            repeat (100) @(posedge clk);

            // Release
            res_rdy <= 1;
            repeat (GAP_BETWEEN) @(posedge clk);

            //--- Test 5: Random backpressure -----------------------
            $display("*** Test 5: random backpressure");
            fork
                // Producer
                begin
                    for (i = 0; i < MANY_CYCLES; i = i + 1) begin
                        a <= $urandom_range(1, 500);
                        b <= $urandom_range(1, 500);
                        c <= $urandom_range(0, 200);
                        arg_vld <= 1;
                        @(posedge clk);
                        while (!arg_rdy) @(posedge clk);
                        if ($urandom_range(0, 4) == 0) begin
                            arg_vld <= 0;
                            repeat ($urandom_range(1, 4)) @(posedge clk);
                        end
                    end
                    arg_vld <= 0;
                end

                // Consumer backpressure
                begin
                    repeat (MANY_CYCLES * 10) begin
                        res_rdy <= $urandom_range(0, 1);
                        @(posedge clk);
                    end
                end
            join_any

            res_rdy <= 1;
            repeat (GAP_BETWEEN * 3) @(posedge clk);

            //--- Test 6: Burst then drain --------------------------
            $display("*** Test 6: burst then drain");
            arg_vld <= 1;
            for (i = 0; i < 30; i = i + 1) begin
                if (arg_rdy) begin
                    a <= 10 + i;
                    b <= 20 + i;
                    c <= 30 + i;
                end
                @(posedge clk);
            end
            arg_vld <= 0;
            repeat (GAP_BETWEEN) @(posedge clk);

            // Verify idle again
            if (arg_rdy !== 1'b1) begin
                $display("FAIL: arg_rdy must return to 1 after drain");
                fail_is_already_reported = 1;
                $finish;
            end
        end
    endtask

    //--------------------------------------------------------------
    // Run
    //--------------------------------------------------------------

    initial begin
        `ifdef __ICARUS__
        $dumpvars;
        `endif
        run();
        $finish;
    end

    //--------------------------------------------------------------
    // Final report
    //--------------------------------------------------------------

    final begin
        $display("\n\nTransfers: arg %0d  res %0d  per %0d cycles",
                 arg_cnt, res_cnt, n_cycles);

        if (arg_cnt == 0)
            $display("FAIL: no input transfers (arg_cnt == 0)");
        else if (res_cnt == 0)
            $display("FAIL: no output transfers (res_cnt == 0)");
        else if (arg_cnt != res_cnt)
            $display("FAIL: arg_cnt (%0d) != res_cnt (%0d)",
                     arg_cnt, res_cnt);
        else if (fail_is_already_reported)
            ;  // already reported
        else if (queue.size() == 0)
            $display("PASS");
        else begin
            $display("FAIL: %0d results still in queue", queue.size());
        end
    end

    //--------------------------------------------------------------
    // Timeout
    //--------------------------------------------------------------

    initial begin
        repeat (TIMEOUT) @(posedge clk);
        $display("FAIL: timeout after %0d cycles", TIMEOUT);
        fail_is_already_reported = 1;
        $finish;
    end

endmodule
