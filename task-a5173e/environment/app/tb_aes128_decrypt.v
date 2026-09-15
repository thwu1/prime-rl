`timescale 1ns/1ps
//
// Testbench for AES-128 Decryption Module
// Tests against NIST reference vectors and encrypt-then-decrypt round-trip

module tb_aes128_decrypt;

    reg clk, rst;

    // ---- Decryption module signals ----
    reg              dec_start;
    reg      [127:0] dec_ct_in, dec_key_in;
    wire     [127:0] dec_pt_out;
    wire             dec_done;

    aes128_decrypt dut_dec(
        .clk(clk), .rst(rst), .start(dec_start),
        .ciphertext(dec_ct_in), .key_in(dec_key_in),
        .plaintext(dec_pt_out), .done(dec_done)
    );

    // ---- Encryption module signals (for round-trip test) ----
    reg              enc_start;
    reg      [127:0] enc_pt_in, enc_key_in;
    wire     [127:0] enc_ct_out;
    wire             enc_done;

    aes128_encrypt dut_enc(
        .clk(clk), .rst(rst), .start(enc_start),
        .plaintext(enc_pt_in), .key_in(enc_key_in),
        .ciphertext(enc_ct_out), .done(enc_done)
    );

    initial clk = 0;
    always #5 clk = ~clk;  // 100 MHz

    integer test_num, pass_cnt, fail_cnt, wc;

    // ----------------------------------------------------------------
    // Task: test direct decryption of a known ciphertext
    // ----------------------------------------------------------------
    task run_decrypt_test;
        input [127:0] ct;
        input [127:0] k;
        input [127:0] expected_pt;
        begin
            dec_ct_in  = ct;
            dec_key_in = k;
            @(posedge clk); #1;
            dec_start = 1;
            @(posedge clk); #1;
            dec_start = 0;

            for (wc = 0; wc < 300; wc = wc + 1) begin
                @(posedge clk); #1;
                if (dec_done) wc = 300;
            end

            if (!dec_done) begin
                $display("[FAIL] Test %0d: TIMEOUT - done never asserted", test_num);
                fail_cnt = fail_cnt + 1;
            end else if (dec_pt_out === expected_pt) begin
                $display("[PASS] Test %0d", test_num);
                pass_cnt = pass_cnt + 1;
            end else begin
                $display("[FAIL] Test %0d", test_num);
                $display("  Expected: %h", expected_pt);
                $display("  Got:      %h", dec_pt_out);
                fail_cnt = fail_cnt + 1;
            end

            test_num = test_num + 1;
            @(posedge clk); #1;
            @(posedge clk); #1;
        end
    endtask

    // ----------------------------------------------------------------
    // Task: encrypt then decrypt and verify round-trip
    // ----------------------------------------------------------------
    task run_roundtrip_test;
        input [127:0] pt;
        input [127:0] k;
        reg roundtrip_ok;
        begin
            roundtrip_ok = 0;

            // Step 1: Encrypt
            enc_pt_in  = pt;
            enc_key_in = k;
            @(posedge clk); #1;
            enc_start = 1;
            @(posedge clk); #1;
            enc_start = 0;

            for (wc = 0; wc < 200; wc = wc + 1) begin
                @(posedge clk); #1;
                if (enc_done) wc = 200;
            end

            if (enc_done) begin
                // Step 2: Decrypt the ciphertext
                @(posedge clk); #1;
                @(posedge clk); #1;
                dec_ct_in  = enc_ct_out;
                dec_key_in = k;
                @(posedge clk); #1;
                dec_start = 1;
                @(posedge clk); #1;
                dec_start = 0;

                for (wc = 0; wc < 300; wc = wc + 1) begin
                    @(posedge clk); #1;
                    if (dec_done) wc = 300;
                end

                if (dec_done && dec_pt_out === pt) begin
                    roundtrip_ok = 1;
                end
            end

            if (roundtrip_ok) begin
                $display("[PASS] Test %0d", test_num);
                pass_cnt = pass_cnt + 1;
            end else begin
                $display("[FAIL] Test %0d", test_num);
                if (!enc_done)
                    $display("  Encrypt TIMEOUT");
                else if (!dec_done)
                    $display("  Decrypt TIMEOUT");
                else begin
                    $display("  Expected: %h", pt);
                    $display("  Got:      %h", dec_pt_out);
                end
                fail_cnt = fail_cnt + 1;
            end

            test_num = test_num + 1;
            @(posedge clk); #1;
            @(posedge clk); #1;
        end
    endtask

    // Global timeout
    initial begin
        #500000;
        $display("[FAIL] Global timeout - simulation exceeded 500us");
        $finish;
    end

    initial begin
        $display("=== AES-128 Decryption Verification ===");
        $display("Testing against NIST reference vectors");
        $display("");

        rst = 1; dec_start = 0; enc_start = 0;
        dec_ct_in = 0; dec_key_in = 0;
        enc_pt_in = 0; enc_key_in = 0;
        test_num = 0; pass_cnt = 0; fail_cnt = 0;

        repeat(5) @(posedge clk);
        #1;
        rst = 0;
        repeat(2) @(posedge clk);
        #1;

        // ----------------------------------------------------------
        // Test 0: FIPS 197 Appendix B (decrypt)
        //   Ciphertext: 3925841d 02dc09fb dc118597 196a0b32
        //   Key:        2b7e1516 28aed2a6 abf71588 09cf4f3c
        //   Expected PT: 3243f6a8 885a308d 313198a2 e0370734
        // ----------------------------------------------------------
        run_decrypt_test(
            128'h3925841d02dc09fbdc118597196a0b32,
            128'h2b7e151628aed2a6abf7158809cf4f3c,
            128'h3243f6a8885a308d313198a2e0370734
        );

        // ----------------------------------------------------------
        // Test 1: NIST SP 800-38A, ECB-AES128 Block 1 (decrypt)
        //   Ciphertext: 3ad77bb4 0d7a3660 a89ecaf3 2466ef97
        //   Key:        2b7e1516 28aed2a6 abf71588 09cf4f3c
        //   Expected PT: 6bc1bee2 2e409f96 e93d7e11 7393172a
        // ----------------------------------------------------------
        run_decrypt_test(
            128'h3ad77bb40d7a3660a89ecaf32466ef97,
            128'h2b7e151628aed2a6abf7158809cf4f3c,
            128'h6bc1bee22e409f96e93d7e117393172a
        );

        // ----------------------------------------------------------
        // Test 2: FIPS 197 Appendix A (AES-128 KAT, decrypt)
        //   Ciphertext: 69c4e0d8 6a7b0430 d8cdb780 70b4c55a
        //   Key:        00010203 04050607 08090a0b 0c0d0e0f
        //   Expected PT: 00112233 44556677 8899aabb ccddeeff
        // ----------------------------------------------------------
        run_decrypt_test(
            128'h69c4e0d86a7b0430d8cdb78070b4c55a,
            128'h000102030405060708090a0b0c0d0e0f,
            128'h00112233445566778899aabbccddeeff
        );

        // ----------------------------------------------------------
        // Test 3: All-zeros (decrypt)
        //   Ciphertext: 66e94bd4 ef8a2c3b 884cfa59 ca342b2e
        //   Key:        00000000 00000000 00000000 00000000
        //   Expected PT: 00000000 00000000 00000000 00000000
        // ----------------------------------------------------------
        run_decrypt_test(
            128'h66e94bd4ef8a2c3b884cfa59ca342b2e,
            128'h00000000000000000000000000000000,
            128'h00000000000000000000000000000000
        );

        // ----------------------------------------------------------
        // Test 4: Round-trip (encrypt then decrypt)
        //   Plaintext:  deadbeef cafebabe 01234567 89abcdef
        //   Key:        0f1e2d3c 4b5a6978 8796a5b4 c3d2e1f0
        // ----------------------------------------------------------
        run_roundtrip_test(
            128'hdeadbeefcafebabe0123456789abcdef,
            128'h0f1e2d3c4b5a69788796a5b4c3d2e1f0
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
