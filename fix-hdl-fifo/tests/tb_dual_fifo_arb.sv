// Dual-channel FIFO arbiter — verification testbench (authoritative copy for testing)

module tb_dual_fifo_arb;
  import fifo_pkg::*;

  logic   clk = 0;
  logic   rst_n;
  logic   ch_a_wr_en, ch_b_wr_en;
  data_t  ch_a_din, ch_b_din;
  logic   ch_a_full, ch_a_almost_full;
  logic   ch_b_full, ch_b_almost_full;
  data_t  out_data;
  logic   out_valid, out_ready;

  dual_fifo_arb u_dut (
    .clk(clk), .rst_n(rst_n),
    .ch_a_wr_en(ch_a_wr_en), .ch_a_din(ch_a_din),
    .ch_a_full(ch_a_full), .ch_a_almost_full(ch_a_almost_full),
    .ch_b_wr_en(ch_b_wr_en), .ch_b_din(ch_b_din),
    .ch_b_full(ch_b_full), .ch_b_almost_full(ch_b_almost_full),
    .out_data(out_data), .out_valid(out_valid), .out_ready(out_ready)
  );

  always #5 clk = ~clk;

  integer errors = 0;
  integer i;
  data_t  expected_val;

  initial begin
    rst_n = 0; ch_a_wr_en = 0; ch_b_wr_en = 0;
    ch_a_din = 0; ch_b_din = 0; out_ready = 0;

    repeat(4) @(posedge clk);
    rst_n = 1;
    @(posedge clk); #1;

    // ---- Test 1: Idle after reset ----
    $display("--- Test 1: Reset state ---");
    if (out_valid) begin $display("FAIL: out_valid asserted after reset"); errors = errors + 1; end

    // ---- Test 2: Channel A only (4 items) ----
    $display("--- Test 2: Channel A only ---");
    for (i = 0; i < 4; i = i + 1) begin
      @(negedge clk);
      ch_a_wr_en = 1;
      ch_a_din = 8'hA0 + i;
    end
    @(negedge clk); ch_a_wr_en = 0;
    @(posedge clk); #1;

    for (i = 0; i < 4; i = i + 1) begin
      @(posedge clk); #1;
      if (!out_valid) begin
        $display("FAIL: T2 out_valid not set for item %0d", i); errors = errors + 1;
      end
      expected_val = 8'hA0 + i;
      if (out_data !== expected_val) begin
        $display("FAIL: T2 item %0d got 0x%02h expected 0x%02h", i, out_data, expected_val);
        errors = errors + 1;
      end
      @(negedge clk); out_ready = 1;
      @(negedge clk); out_ready = 0;
    end
    @(posedge clk); #1;
    if (out_valid) begin $display("FAIL: T2 out_valid set after drain"); errors = errors + 1; end

    // ---- Reset for Test 3 ----
    ch_a_wr_en = 0; ch_b_wr_en = 0; out_ready = 0;
    rst_n = 0; repeat(4) @(posedge clk); rst_n = 1;
    @(posedge clk); #1;

    // ---- Test 3: Channel B only (4 items) ----
    $display("--- Test 3: Channel B only ---");
    for (i = 0; i < 4; i = i + 1) begin
      @(negedge clk);
      ch_b_wr_en = 1;
      ch_b_din = 8'hB0 + i;
    end
    @(negedge clk); ch_b_wr_en = 0;
    @(posedge clk); #1;

    for (i = 0; i < 4; i = i + 1) begin
      @(posedge clk); #1;
      if (!out_valid) begin
        $display("FAIL: T3 out_valid not set for item %0d", i); errors = errors + 1;
      end
      expected_val = 8'hB0 + i;
      if (out_data !== expected_val) begin
        $display("FAIL: T3 item %0d got 0x%02h expected 0x%02h", i, out_data, expected_val);
        errors = errors + 1;
      end
      @(negedge clk); out_ready = 1;
      @(negedge clk); out_ready = 0;
    end
    @(posedge clk); #1;
    if (out_valid) begin $display("FAIL: T3 out_valid set after drain"); errors = errors + 1; end

    // ---- Reset for Test 4 ----
    ch_a_wr_en = 0; ch_b_wr_en = 0; out_ready = 0;
    rst_n = 0; repeat(4) @(posedge clk); rst_n = 1;
    @(posedge clk); #1;

    // ---- Test 4: Round-robin interleaving ----
    $display("--- Test 4: Round-robin ---");
    for (i = 0; i < 4; i = i + 1) begin
      @(negedge clk);
      ch_a_wr_en = 1; ch_b_wr_en = 1;
      ch_a_din = 8'hA0 + i;
      ch_b_din = 8'hB0 + i;
    end
    @(negedge clk); ch_a_wr_en = 0; ch_b_wr_en = 0;
    @(posedge clk); #1;

    // Expected order: A0, B0, A1, B1, A2, B2, A3, B3
    for (i = 0; i < 8; i = i + 1) begin
      @(posedge clk); #1;
      if (!out_valid) begin
        $display("FAIL: T4 out_valid not set for item %0d", i); errors = errors + 1;
      end
      if (i % 2 == 0)
        expected_val = 8'hA0 + i / 2;
      else
        expected_val = 8'hB0 + i / 2;
      if (out_data !== expected_val) begin
        $display("FAIL: T4 item %0d got 0x%02h expected 0x%02h", i, out_data, expected_val);
        errors = errors + 1;
      end
      @(negedge clk); out_ready = 1;
      @(negedge clk); out_ready = 0;
    end
    @(posedge clk); #1;
    if (out_valid) begin $display("FAIL: T4 out_valid set after drain"); errors = errors + 1; end

    // ---- Reset for Test 5 ----
    ch_a_wr_en = 0; ch_b_wr_en = 0; out_ready = 0;
    rst_n = 0; repeat(4) @(posedge clk); rst_n = 1;
    @(posedge clk); #1;

    // ---- Test 5: Backpressure ----
    $display("--- Test 5: Backpressure ---");
    for (i = 0; i < 2; i = i + 1) begin
      @(negedge clk);
      ch_a_wr_en = 1;
      ch_a_din = 8'hC0 + i;
    end
    @(negedge clk); ch_a_wr_en = 0;
    @(posedge clk); #1;

    // Verify data available but held
    @(posedge clk); #1;
    if (!out_valid) begin $display("FAIL: T5 data not available"); errors = errors + 1; end
    if (out_data !== 8'hC0) begin
      $display("FAIL: T5 initial data 0x%02h expected 0xC0", out_data); errors = errors + 1;
    end

    // Hold backpressure for several cycles
    repeat(4) @(posedge clk);
    @(posedge clk); #1;
    if (out_data !== 8'hC0) begin
      $display("FAIL: T5 data changed under backpressure to 0x%02h", out_data); errors = errors + 1;
    end

    // Consume first item
    @(negedge clk); out_ready = 1;
    @(negedge clk); out_ready = 0;
    @(posedge clk); #1;
    if (out_data !== 8'hC1) begin
      $display("FAIL: T5 second item 0x%02h expected 0xC1", out_data); errors = errors + 1;
    end

    // Consume second item
    @(negedge clk); out_ready = 1;
    @(negedge clk); out_ready = 0;
    @(posedge clk); #1;
    if (out_valid) begin $display("FAIL: T5 should be empty after drain"); errors = errors + 1; end

    // ---- Reset for Test 6 ----
    ch_a_wr_en = 0; ch_b_wr_en = 0; out_ready = 0;
    rst_n = 0; repeat(4) @(posedge clk); rst_n = 1;
    @(posedge clk); #1;

    // ---- Test 6: Full flag and data integrity ----
    $display("--- Test 6: Full flag ---");
    for (i = 0; i < FIFO_DEPTH; i = i + 1) begin
      @(negedge clk);
      ch_a_wr_en = 1;
      ch_a_din = i[DATA_WIDTH-1:0];
    end
    @(negedge clk); ch_a_wr_en = 0;
    @(posedge clk); #1;

    if (!ch_a_full) begin
      $display("FAIL: T6 ch_a_full not set after %0d writes", FIFO_DEPTH); errors = errors + 1;
    end
    if (!ch_a_almost_full) begin
      $display("FAIL: T6 ch_a_almost_full not set when full"); errors = errors + 1;
    end

    // Write when full should be rejected
    @(negedge clk);
    ch_a_wr_en = 1;
    ch_a_din = 8'hFF;
    @(negedge clk); ch_a_wr_en = 0;

    // Read all items through arbiter, verify FIFO order (0xFF must not appear)
    for (i = 0; i < FIFO_DEPTH; i = i + 1) begin
      @(posedge clk); #1;
      expected_val = i[DATA_WIDTH-1:0];
      if (out_data !== expected_val) begin
        $display("FAIL: T6 item %0d got 0x%02h expected 0x%02h", i, out_data, expected_val);
        errors = errors + 1;
      end
      @(negedge clk); out_ready = 1;
      @(negedge clk); out_ready = 0;
    end

    // ---- Summary ----
    if (errors == 0)
      $display("PASS: All tests passed");
    else
      $display("FAIL: %0d errors detected", errors);

    $finish;
  end

  // Timeout watchdog
  initial begin
    #500000;
    $display("FAIL: Simulation timeout");
    $finish;
  end

endmodule
