`timescale 1ns/1ps
//
// Testbench for AES-128 Encryption Module
// Uses NIST-standard test vectors for verification

module tb_aes128;

    reg              clk, rst, start;
    reg      [127:0] plaintext, key_in;
    wire     [127:0] ciphertext;
    wire             done;

    aes128_encrypt dut (
        .clk(clk), .rst(rst), .start(start),
        .plaintext(plaintext), .key_in(key_in),
        .ciphertext(ciphertext), .done(done)
    );

    initial clk = 0;
    always #5 clk = ~clk;  // 100 MHz

    integer test_num, pass_cnt, fail_cnt, wc;

    task run_test;
        input [127:0] pt;
        input [127:0] k;
        input [127:0] expected;
        begin
            // Set inputs
            plaintext = pt;
            key_in = k;

            // Pulse start for one cycle
            @(posedge clk);
            #1;
            start = 1;
            @(posedge clk);
            #1;
            start = 0;

            // Wait for done (timeout after 200 cycles)
            for (wc = 0; wc < 200; wc = wc + 1) begin
                @(posedge clk);
                #1;
                if (done) wc = 200;
            end

            if (!done) begin
                $display("[FAIL] Test %0d: TIMEOUT - done never asserted", test_num);
                fail_cnt = fail_cnt + 1;
            end else if (ciphertext === expected) begin
                $display("[PASS] Test %0d", test_num);
                pass_cnt = pass_cnt + 1;
            end else begin
                $display("[FAIL] Test %0d", test_num);
                $display("  Expected: %h", expected);
                $display("  Got:      %h", ciphertext);
                fail_cnt = fail_cnt + 1;
            end

            test_num = test_num + 1;

            // Wait for FSM to return to IDLE
            @(posedge clk); #1;
            @(posedge clk); #1;
        end
    endtask

    // Global timeout
    initial begin
        #200000;
        $display("[FAIL] Global timeout - simulation exceeded 200us");
        $finish;
    end

    initial begin
        $display("=== AES-128 Encryption Verification ===");
        $display("Testing against NIST reference vectors");
        $display("");

        rst = 1; start = 0; plaintext = 0; key_in = 0;
        test_num = 0; pass_cnt = 0; fail_cnt = 0;

        // Hold reset for several cycles
        repeat(5) @(posedge clk);
        #1;
        rst = 0;
        repeat(2) @(posedge clk);
        #1;

        // ----------------------------------------------------------
        // Test 0: FIPS 197 Appendix B
        //   Plaintext: 3243f6a8 885a308d 313198a2 e0370734
        //   Key:       2b7e1516 28aed2a6 abf71588 09cf4f3c
        //   Expected:  3925841d 02dc09fb dc118597 196a0b32
        // ----------------------------------------------------------
        run_test(
            128'h3243f6a8885a308d313198a2e0370734,
            128'h2b7e151628aed2a6abf7158809cf4f3c,
            128'h3925841d02dc09fbdc118597196a0b32
        );

        // ----------------------------------------------------------
        // Test 1: NIST SP 800-38A, ECB-AES128, Block 1
        //   Plaintext: 6bc1bee2 2e409f96 e93d7e11 7393172a
        //   Key:       2b7e1516 28aed2a6 abf71588 09cf4f3c
        //   Expected:  3ad77bb4 0d7a3660 a89ecaf3 2466ef97
        // ----------------------------------------------------------
        run_test(
            128'h6bc1bee22e409f96e93d7e117393172a,
            128'h2b7e151628aed2a6abf7158809cf4f3c,
            128'h3ad77bb40d7a3660a89ecaf32466ef97
        );

        // ----------------------------------------------------------
        // Test 2: FIPS 197 Appendix A (AES-128 Known Answer Test)
        //   Plaintext: 00112233 44556677 8899aabb ccddeeff
        //   Key:       00010203 04050607 08090a0b 0c0d0e0f
        //   Expected:  69c4e0d8 6a7b0430 d8cdb780 70b4c55a
        // ----------------------------------------------------------
        run_test(
            128'h00112233445566778899aabbccddeeff,
            128'h000102030405060708090a0b0c0d0e0f,
            128'h69c4e0d86a7b0430d8cdb78070b4c55a
        );

        // ----------------------------------------------------------
        // Test 3: All-zeros
        //   Plaintext: 00000000 00000000 00000000 00000000
        //   Key:       00000000 00000000 00000000 00000000
        //   Expected:  66e94bd4 ef8a2c3b 884cfa59 ca342b2e
        // ----------------------------------------------------------
        run_test(
            128'h00000000000000000000000000000000,
            128'h00000000000000000000000000000000,
            128'h66e94bd4ef8a2c3b884cfa59ca342b2e
        );

        // Summary
        $display("");
        $display("==================================");
        $display("Total: %0d, Passed: %0d, Failed: %0d", test_num, pass_cnt, fail_cnt);
        if (pass_cnt == test_num)
            $display("ALL TESTS PASSED");
        else
            $display("SOME TESTS FAILED");
        $display("==================================");
        $finish;
    end

endmodule
