// Memory model for MaxiCore32 testbench
// Pre-loaded with a test program that exercises operand forwarding
//
// The program contains consecutive dependent instructions WITHOUT NOP delay slots.
// Without operand forwarding, data hazards cause incorrect register values.
//
// Expected register values after HALT (with correct forwarding):
//   r1  = 0x0000002A (42)     - loadi.u r1, 42
//   r2  = 0x00000054 (84)     - add r2, r1, r1       [forwards r1 from LOADI to both operands]
//   r3  = 0x0000007E (126)    - add r3, r2, r1       [forwards r2 from ALU]
//   r4  = 0x00000054 (84)     - sub r4, r3, r1       [forwards r3 from ALU]
//   r5  = 0x000000C8 (200)    - loadi.u r5, 200
//   r6  = 0x000000FA (250)    - add r6, r5, 50       [forwards r5 from LOADI, immediate operand]
//   r7  = 0x000000A6 (166)    - sub r7, r6, r4       [forwards r6 from ALUMI result]
//   r8  = 0xFFFFFFF1 (-15)    - loadi.s r8, -15
//   r9  = 0x000000B9 (185)    - add r9, r8, r5       [forwards r8 from signed LOADI]
//   r10 = 0x00000007 (7)      - loadi.u r10, 7
//   r11 = 0x00000031 (49)     - mulu r11, r10, r10   [forwards r10 to both operands]
//   r12 = 0xFFFFFFCE (~49)    - not r12, r11         [forwards r11 from ALU, single-operand op]

module memory
    (
        input clock,
        input cs,
        input [31:2] address,
        input [31:0] data_in,
        output reg [31:0] data_out,
        input [3:0] data_strobes,
        input read,
        input write
    );

    reg [31:0] contents [0:1023];

    wire [9:0] word_addr = address[11:2];

    integer i;
    initial begin
        for (i = 0; i < 1024; i = i + 1)
            contents[i] = 32'h00000000;

        // === Test Program: Operand Forwarding Verification ===
        // Each pair of instructions creates a data hazard (no NOP between them)

        // Block 1: LOADI.u -> ALU forwarding (both operands)
        contents[0]  = 32'h1410002A; // loadi.u r1, 42
        contents[1]  = 32'h38210100; // add r2, r1, r1          ; r2 = 42+42 = 84

        // Block 2: ALU -> ALU chain forwarding
        contents[2]  = 32'h38320100; // add r3, r2, r1          ; r3 = 84+42 = 126 (forward r2)
        contents[3]  = 32'h38432100; // sub r4, r3, r1          ; r4 = 126-42 = 84 (forward r3)

        // Gap to separate test blocks
        contents[4]  = 32'h00000000; // nop
        contents[5]  = 32'h00000000; // nop

        // Block 3: LOADI.u -> ALUMI forwarding (immediate second operand)
        contents[6]  = 32'h145000C8; // loadi.u r5, 200
        contents[7]  = 32'h40650032; // add r6, r5, 50          ; r6 = 200+50 = 250 (forward r5)

        // Block 4: ALUMI -> ALU forwarding
        contents[8]  = 32'h38762400; // sub r7, r6, r4          ; r7 = 250-84 = 166 (forward r6)

        // Gap
        contents[9]  = 32'h00000000; // nop
        contents[10] = 32'h00000000; // nop

        // Block 5: LOADI.s (signed) -> ALU forwarding
        contents[11] = 32'h1680FFF1; // loadi.s r8, -15
        contents[12] = 32'h38980500; // add r9, r8, r5          ; r9 = -15+200 = 185 (forward r8)

        // Gap
        contents[13] = 32'h00000000; // nop
        contents[14] = 32'h00000000; // nop

        // Block 6: LOADI.u -> MULU forwarding (both operands same register)
        contents[15] = 32'h14A00007; // loadi.u r10, 7
        contents[16] = 32'h38BA9A00; // mulu r11, r10, r10      ; r11 = 7*7 = 49 (forward r10)

        // Block 7: ALU -> single-operand ALU forwarding
        contents[17] = 32'h48CB0000; // not r12, r11            ; r12 = ~49 (forward r11)

        // Gap + halt
        contents[18] = 32'h00000000; // nop
        contents[19] = 32'h00000000; // nop
        contents[20] = 32'h08000000; // halt
    end

    // Combinational read
    always @(*) begin
        if (cs && read) begin
            data_out = contents[word_addr];
        end else begin
            data_out = 32'h0;
        end
    end

    // Synchronous write with byte strobes
    always @(posedge clock) begin
        if (cs && write) begin
            if (data_strobes[3]) contents[word_addr][31:24] <= data_in[31:24];
            if (data_strobes[2]) contents[word_addr][23:16] <= data_in[23:16];
            if (data_strobes[1]) contents[word_addr][15:8]  <= data_in[15:8];
            if (data_strobes[0]) contents[word_addr][7:0]   <= data_in[7:0];
        end
    end
endmodule
