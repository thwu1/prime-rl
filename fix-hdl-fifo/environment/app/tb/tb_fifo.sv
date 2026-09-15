// Synchronous FIFO — verification testbench

module tb_fifo;
  import fifo_pkg::*;

  logic   clk = 0;
  logic   rst_n;
  logic   wr_en, rd_en;
  data_t  din, dout;
  logic   full, empty, almost_full, almost_empty;

  fifo u_dut (
    .clk(clk), .rst_n(rst_n),
    .wr_en(wr_en), .rd_en(rd_en),
    .din(din), .dout(dout),
    .full(full), .empty(empty),
    .almost_full(almost_full), .almost_empty(almost_empty)
  );

  always #5 clk = ~clk;

  integer errors = 0;
  integer i;

  initial begin
    rst_n = 0; wr_en = 0; rd_en = 0; din = '0;

    // Reset
    repeat(4) @(posedge clk);
    rst_n = 1;
    @(posedge clk); #1;

    // ---- Test 1: Empty after reset ----
    if (!empty) begin $display("FAIL: not empty after reset"); errors = errors + 1; end
    if (full)   begin $display("FAIL: full after reset"); errors = errors + 1; end

    // ---- Test 2: Write FIFO_DEPTH items ----
    for (i = 0; i < FIFO_DEPTH; i = i + 1) begin
      @(negedge clk);
      wr_en = 1;
      din = i[DATA_WIDTH-1:0];
    end
    @(negedge clk);
    wr_en = 0;
    @(posedge clk); #1;

    if (!full)  begin $display("FAIL: not full after %0d writes", FIFO_DEPTH); errors = errors + 1; end
    if (empty)  begin $display("FAIL: empty when should be full"); errors = errors + 1; end
    if (!almost_full) begin $display("FAIL: almost_full not set when full"); errors = errors + 1; end

    // ---- Test 3: Write when full should be ignored ----
    @(negedge clk);
    wr_en = 1;
    din = 8'hFF;
    @(negedge clk);
    wr_en = 0;
    @(posedge clk); #1;

    // ---- Test 4: Read all items, verify FIFO order ----
    for (i = 0; i < FIFO_DEPTH; i = i + 1) begin
      @(posedge clk); #1;
      if (dout !== i[DATA_WIDTH-1:0]) begin
        $display("FAIL: read[%0d] got 0x%h expected 0x%h", i, dout, i[DATA_WIDTH-1:0]);
        errors = errors + 1;
      end
      @(negedge clk);
      rd_en = 1;
    end
    @(negedge clk);
    rd_en = 0;
    @(posedge clk); #1;

    if (!empty) begin $display("FAIL: not empty after reading all items"); errors = errors + 1; end
    if (full)   begin $display("FAIL: still full after reading all items"); errors = errors + 1; end

    // ---- Test 5: Almost-full threshold ----
    for (i = 0; i < AFULL_THRESH; i = i + 1) begin
      @(negedge clk);
      wr_en = 1;
      din = i[DATA_WIDTH-1:0];
    end
    @(negedge clk);
    wr_en = 0;
    @(posedge clk); #1;

    if (!almost_full) begin
      $display("FAIL: almost_full not set at threshold %0d", AFULL_THRESH);
      errors = errors + 1;
    end

    // ---- Test 6: Drain to almost-empty threshold ----
    for (i = 0; i < AFULL_THRESH - AEMPTY_THRESH; i = i + 1) begin
      @(negedge clk);
      rd_en = 1;
    end
    @(negedge clk);
    rd_en = 0;
    @(posedge clk); #1;

    if (!almost_empty) begin
      $display("FAIL: almost_empty not set with %0d items remaining", AEMPTY_THRESH);
      errors = errors + 1;
    end
    if (almost_full) begin
      $display("FAIL: almost_full incorrectly set with only %0d items", AEMPTY_THRESH);
      errors = errors + 1;
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
    #200000;
    $display("FAIL: Simulation timeout");
    $finish;
  end

endmodule
