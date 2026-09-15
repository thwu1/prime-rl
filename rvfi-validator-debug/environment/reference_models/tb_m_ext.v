// tb_m_ext.v - Testbench for RV32M reference models
// Exercises all 8 M-extension instructions with edge-case inputs.
// Compile: iverilog -o m_ref_sim m_ref.v tb_m_ext.v
// Run:     vvp m_ref_sim

`timescale 1ns/1ps

module tb;
    reg [31:0] rs1, rs2;
    wire [31:0] rd_mul, rd_mulh, rd_mulhu, rd_mulhsu;
    wire [31:0] rd_div, rd_divu, rd_rem, rd_remu;

    mul_ref    u_mul   (.rs1(rs1), .rs2(rs2), .rd(rd_mul));
    mulh_ref   u_mulh  (.rs1(rs1), .rs2(rs2), .rd(rd_mulh));
    mulhu_ref  u_mulhu (.rs1(rs1), .rs2(rs2), .rd(rd_mulhu));
    mulhsu_ref u_mulhsu(.rs1(rs1), .rs2(rs2), .rd(rd_mulhsu));
    div_ref    u_div   (.rs1(rs1), .rs2(rs2), .rd(rd_div));
    divu_ref   u_divu  (.rs1(rs1), .rs2(rs2), .rd(rd_divu));
    rem_ref    u_rem   (.rs1(rs1), .rs2(rs2), .rd(rd_rem));
    remu_ref   u_remu  (.rs1(rs1), .rs2(rs2), .rd(rd_remu));

    task run_test;
        input [31:0] a, b;
        begin
            rs1 = a; rs2 = b; #1;
            $display("=== rs1=0x%h  rs2=0x%h ===", rs1, rs2);
            $display("  MUL    = 0x%h", rd_mul);
            $display("  MULH   = 0x%h", rd_mulh);
            $display("  MULHU  = 0x%h", rd_mulhu);
            $display("  MULHSU = 0x%h", rd_mulhsu);
            $display("  DIV    = 0x%h", rd_div);
            $display("  DIVU   = 0x%h", rd_divu);
            $display("  REM    = 0x%h", rd_rem);
            $display("  REMU   = 0x%h", rd_remu);
            $display("");
        end
    endtask

    initial begin
        $display("");
        $display("RV32M Reference Model — Edge Case Test Results");
        $display("===============================================");
        $display("");

        // Basic small positive multiply
        $display("[1] Basic positive:");
        run_test(32'd6, 32'd7);

        // Negative x positive (signed: -7 x 7 = -49)
        $display("[2] Negative x positive (signed -7 x 7):");
        run_test(32'hfffffff9, 32'd7);

        // Negative x negative (signed: -3 x -5 = 15)
        $display("[3] Negative x negative (signed -3 x -5):");
        run_test(32'hfffffffd, 32'hfffffffb);

        // Large unsigned (0xFFFFFFFF x 0xFFFFFFFF)
        $display("[4] Large unsigned (max x max):");
        run_test(32'hffffffff, 32'hffffffff);

        // Signed overflow: MIN_INT / -1
        $display("[5] Signed overflow (MIN_INT / -1):");
        run_test(32'h80000000, 32'hffffffff);

        // Division by zero
        $display("[6] Division by zero:");
        run_test(32'd42, 32'd0);

        // Signed division: -13 / 5 = -2 rem -3
        $display("[7] Signed division (-13 / 5):");
        run_test(32'hfffffff3, 32'd5);

        // MULHSU: signed(-1) x unsigned(0x80000000)
        $display("[8] MULHSU edge (-1 x 0x80000000):");
        run_test(32'hffffffff, 32'h80000000);

        // MULHSU: signed(2) x unsigned(0x80000000)
        $display("[9] MULHSU edge (2 x 0x80000000):");
        run_test(32'd2, 32'h80000000);

        // Zero operands
        $display("[10] Zero x anything:");
        run_test(32'd0, 32'd12345);

        $finish;
    end
endmodule
