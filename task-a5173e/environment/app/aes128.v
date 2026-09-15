`timescale 1ns/1ps
//
// AES-128 Encryption Module
// Sequential FSM: one round per clock cycle, 10 rounds total

module aes128_encrypt(
    input              clk,
    input              rst,
    input              start,
    input      [127:0] plaintext,
    input      [127:0] key_in,
    output reg [127:0] ciphertext,
    output reg         done
);

    // ================================================================
    // AES S-Box (FIPS 197, Section 5.1.1)
    // ================================================================
    function [7:0] sbox;
        input [7:0] in;
        begin
            case (in)
                8'h00: sbox=8'h63; 8'h01: sbox=8'h7c; 8'h02: sbox=8'h77; 8'h03: sbox=8'h7b;
                8'h04: sbox=8'hf2; 8'h05: sbox=8'h6b; 8'h06: sbox=8'h6f; 8'h07: sbox=8'hc5;
                8'h08: sbox=8'h30; 8'h09: sbox=8'h01; 8'h0a: sbox=8'h67; 8'h0b: sbox=8'h2b;
                8'h0c: sbox=8'hfe; 8'h0d: sbox=8'hd7; 8'h0e: sbox=8'hab; 8'h0f: sbox=8'h76;
                8'h10: sbox=8'hca; 8'h11: sbox=8'h82; 8'h12: sbox=8'hc9; 8'h13: sbox=8'h7d;
                8'h14: sbox=8'hfa; 8'h15: sbox=8'h59; 8'h16: sbox=8'h47; 8'h17: sbox=8'hf0;
                8'h18: sbox=8'had; 8'h19: sbox=8'hd4; 8'h1a: sbox=8'ha2; 8'h1b: sbox=8'haf;
                8'h1c: sbox=8'h9c; 8'h1d: sbox=8'ha4; 8'h1e: sbox=8'h72; 8'h1f: sbox=8'hc0;
                8'h20: sbox=8'hb7; 8'h21: sbox=8'hfd; 8'h22: sbox=8'h93; 8'h23: sbox=8'h26;
                8'h24: sbox=8'h36; 8'h25: sbox=8'h3f; 8'h26: sbox=8'hf7; 8'h27: sbox=8'hcc;
                8'h28: sbox=8'h34; 8'h29: sbox=8'ha5; 8'h2a: sbox=8'he5; 8'h2b: sbox=8'hf1;
                8'h2c: sbox=8'h71; 8'h2d: sbox=8'hd8; 8'h2e: sbox=8'h31; 8'h2f: sbox=8'h15;
                8'h30: sbox=8'h04; 8'h31: sbox=8'hc7; 8'h32: sbox=8'h23; 8'h33: sbox=8'hc3;
                8'h34: sbox=8'h18; 8'h35: sbox=8'h96; 8'h36: sbox=8'h05; 8'h37: sbox=8'h9a;
                8'h38: sbox=8'h07; 8'h39: sbox=8'h12; 8'h3a: sbox=8'h80; 8'h3b: sbox=8'he2;
                8'h3c: sbox=8'heb; 8'h3d: sbox=8'h27; 8'h3e: sbox=8'hb2; 8'h3f: sbox=8'h75;
                8'h40: sbox=8'h09; 8'h41: sbox=8'h83; 8'h42: sbox=8'h2c; 8'h43: sbox=8'h1a;
                8'h44: sbox=8'h1b; 8'h45: sbox=8'h6e; 8'h46: sbox=8'h5a; 8'h47: sbox=8'ha0;
                8'h48: sbox=8'h52; 8'h49: sbox=8'h3b; 8'h4a: sbox=8'hd6; 8'h4b: sbox=8'hb3;
                8'h4c: sbox=8'h29; 8'h4d: sbox=8'he3; 8'h4e: sbox=8'h2f; 8'h4f: sbox=8'h84;
                8'h50: sbox=8'h53; 8'h51: sbox=8'hd1; 8'h52: sbox=8'h00; 8'h53: sbox=8'hed;
                8'h54: sbox=8'h20; 8'h55: sbox=8'hfc; 8'h56: sbox=8'hb1; 8'h57: sbox=8'h5b;
                8'h58: sbox=8'h6a; 8'h59: sbox=8'hcb; 8'h5a: sbox=8'hbe; 8'h5b: sbox=8'h39;
                8'h5c: sbox=8'h4a; 8'h5d: sbox=8'h4c; 8'h5e: sbox=8'h58; 8'h5f: sbox=8'hcf;
                8'h60: sbox=8'hd0; 8'h61: sbox=8'hef; 8'h62: sbox=8'haa; 8'h63: sbox=8'hfb;
                8'h64: sbox=8'h43; 8'h65: sbox=8'h4d; 8'h66: sbox=8'h33; 8'h67: sbox=8'h85;
                8'h68: sbox=8'h45; 8'h69: sbox=8'hf9; 8'h6a: sbox=8'h02; 8'h6b: sbox=8'h7f;
                8'h6c: sbox=8'h50; 8'h6d: sbox=8'h3c; 8'h6e: sbox=8'h9f; 8'h6f: sbox=8'ha8;
                8'h70: sbox=8'h51; 8'h71: sbox=8'ha3; 8'h72: sbox=8'h40; 8'h73: sbox=8'h8f;
                8'h74: sbox=8'h92; 8'h75: sbox=8'h9d; 8'h76: sbox=8'h38; 8'h77: sbox=8'hf5;
                8'h78: sbox=8'hbc; 8'h79: sbox=8'hb6; 8'h7a: sbox=8'hda; 8'h7b: sbox=8'h21;
                8'h7c: sbox=8'h10; 8'h7d: sbox=8'hff; 8'h7e: sbox=8'hf3; 8'h7f: sbox=8'hd2;
                8'h80: sbox=8'hcd; 8'h81: sbox=8'h0c; 8'h82: sbox=8'h13; 8'h83: sbox=8'hec;
                8'h84: sbox=8'h5f; 8'h85: sbox=8'h97; 8'h86: sbox=8'h44; 8'h87: sbox=8'h17;
                8'h88: sbox=8'hc4; 8'h89: sbox=8'ha7; 8'h8a: sbox=8'h7e; 8'h8b: sbox=8'h3d;
                8'h8c: sbox=8'h64; 8'h8d: sbox=8'h5d; 8'h8e: sbox=8'h19; 8'h8f: sbox=8'h73;
                8'h90: sbox=8'h60; 8'h91: sbox=8'h81; 8'h92: sbox=8'h4f; 8'h93: sbox=8'hdc;
                8'h94: sbox=8'h22; 8'h95: sbox=8'h2a; 8'h96: sbox=8'h90; 8'h97: sbox=8'h88;
                8'h98: sbox=8'h46; 8'h99: sbox=8'hee; 8'h9a: sbox=8'hb8; 8'h9b: sbox=8'h14;
                8'h9c: sbox=8'hde; 8'h9d: sbox=8'h5e; 8'h9e: sbox=8'h0b; 8'h9f: sbox=8'hdb;
                8'ha0: sbox=8'he0; 8'ha1: sbox=8'h32; 8'ha2: sbox=8'h3a; 8'ha3: sbox=8'h0a;
                8'ha4: sbox=8'h49; 8'ha5: sbox=8'h06; 8'ha6: sbox=8'h24; 8'ha7: sbox=8'h5c;
                8'ha8: sbox=8'hc2; 8'ha9: sbox=8'hd3; 8'haa: sbox=8'hac; 8'hab: sbox=8'h62;
                8'hac: sbox=8'h91; 8'had: sbox=8'h95; 8'hae: sbox=8'he4; 8'haf: sbox=8'h79;
                8'hb0: sbox=8'he7; 8'hb1: sbox=8'hc8; 8'hb2: sbox=8'h37; 8'hb3: sbox=8'h6d;
                8'hb4: sbox=8'h8d; 8'hb5: sbox=8'hd5; 8'hb6: sbox=8'h4e; 8'hb7: sbox=8'ha9;
                8'hb8: sbox=8'h6c; 8'hb9: sbox=8'h56; 8'hba: sbox=8'hf4; 8'hbb: sbox=8'hea;
                8'hbc: sbox=8'h65; 8'hbd: sbox=8'h7a; 8'hbe: sbox=8'hae; 8'hbf: sbox=8'h08;
                8'hc0: sbox=8'hba; 8'hc1: sbox=8'h78; 8'hc2: sbox=8'h25; 8'hc3: sbox=8'h2e;
                8'hc4: sbox=8'h1c; 8'hc5: sbox=8'ha6; 8'hc6: sbox=8'hb4; 8'hc7: sbox=8'hc6;
                8'hc8: sbox=8'he8; 8'hc9: sbox=8'hdd; 8'hca: sbox=8'h74; 8'hcb: sbox=8'h1f;
                8'hcc: sbox=8'h4b; 8'hcd: sbox=8'hbd; 8'hce: sbox=8'h8b; 8'hcf: sbox=8'h8a;
                8'hd0: sbox=8'h70; 8'hd1: sbox=8'h3e; 8'hd2: sbox=8'hb5; 8'hd3: sbox=8'h66;
                8'hd4: sbox=8'h48; 8'hd5: sbox=8'h03; 8'hd6: sbox=8'hf6; 8'hd7: sbox=8'h0e;
                8'hd8: sbox=8'h61; 8'hd9: sbox=8'h35; 8'hda: sbox=8'h57; 8'hdb: sbox=8'hb9;
                8'hdc: sbox=8'h86; 8'hdd: sbox=8'hc1; 8'hde: sbox=8'h1d; 8'hdf: sbox=8'h9e;
                8'he0: sbox=8'he1; 8'he1: sbox=8'hf8; 8'he2: sbox=8'h98; 8'he3: sbox=8'h11;
                8'he4: sbox=8'h69; 8'he5: sbox=8'hd9; 8'he6: sbox=8'h8e; 8'he7: sbox=8'h94;
                8'he8: sbox=8'h9b; 8'he9: sbox=8'h1e; 8'hea: sbox=8'h87; 8'heb: sbox=8'he9;
                8'hec: sbox=8'hce; 8'hed: sbox=8'h55; 8'hee: sbox=8'h28; 8'hef: sbox=8'hdf;
                8'hf0: sbox=8'h8c; 8'hf1: sbox=8'ha1; 8'hf2: sbox=8'h89; 8'hf3: sbox=8'h0d;
                8'hf4: sbox=8'hbf; 8'hf5: sbox=8'he6; 8'hf6: sbox=8'h42; 8'hf7: sbox=8'h68;
                8'hf8: sbox=8'h41; 8'hf9: sbox=8'h99; 8'hfa: sbox=8'h2d; 8'hfb: sbox=8'h0f;
                8'hfc: sbox=8'hb0; 8'hfd: sbox=8'h54; 8'hfe: sbox=8'hbb; 8'hff: sbox=8'h16;
                default: sbox = 8'h00;
            endcase
        end
    endfunction

    // ================================================================
    // GF(2^8) Arithmetic
    // ================================================================
    function [7:0] xtime;
        input [7:0] b;
        begin
            xtime = {b[6:0], 1'b0} ^ (8'h1d & {8{b[7]}});
        end
    endfunction

    function [7:0] gf_mul2;
        input [7:0] b;
        begin
            gf_mul2 = xtime(b);
        end
    endfunction

    function [7:0] gf_mul3;
        input [7:0] b;
        begin
            gf_mul3 = xtime(b) ^ b;
        end
    endfunction

    // ================================================================
    // SubBytes: Apply S-box to every byte of the state
    // ================================================================
    function [127:0] sub_bytes;
        input [127:0] state;
        begin
            sub_bytes = {
                sbox(state[127:120]), sbox(state[119:112]),
                sbox(state[111:104]), sbox(state[103:96]),
                sbox(state[95:88]),   sbox(state[87:80]),
                sbox(state[79:72]),   sbox(state[71:64]),
                sbox(state[63:56]),   sbox(state[55:48]),
                sbox(state[47:40]),   sbox(state[39:32]),
                sbox(state[31:24]),   sbox(state[23:16]),
                sbox(state[15:8]),    sbox(state[7:0])
            };
        end
    endfunction

    // ================================================================
    // ShiftRows: Circular left-shift each row by its row index
    // ================================================================
    function [127:0] shift_rows;
        input [127:0] state;
        reg [7:0] s0, s1, s2, s3, s4, s5, s6, s7;
        reg [7:0] s8, s9, s10, s11, s12, s13, s14, s15;
        begin
            s0 =state[127:120]; s1 =state[119:112];
            s2 =state[111:104]; s3 =state[103:96];
            s4 =state[95:88];   s5 =state[87:80];
            s6 =state[79:72];   s7 =state[71:64];
            s8 =state[63:56];   s9 =state[55:48];
            s10=state[47:40];   s11=state[39:32];
            s12=state[31:24];   s13=state[23:16];
            s14=state[15:8];    s15=state[7:0];

            // State matrix (column-major): byte index = row + 4*col
            //   col0  col1  col2  col3
            //   s0    s4    s8    s12     row 0
            //   s1    s5    s9    s13     row 1
            //   s2    s6    s10   s14     row 2
            //   s3    s7    s11   s15     row 3
            shift_rows = {
                s0,  s5,  s10, s7,
                s4,  s9,  s14, s11,
                s8,  s13, s2,  s15,
                s12, s1,  s6,  s3
            };
        end
    endfunction

    // ================================================================
    // MixColumns: GF(2^8) matrix multiplication on each column
    // ================================================================
    function [127:0] mix_columns;
        input [127:0] state;
        reg [7:0] s0, s1, s2, s3, s4, s5, s6, s7;
        reg [7:0] s8, s9, s10, s11, s12, s13, s14, s15;
        reg [7:0] r0, r1, r2, r3, r4, r5, r6, r7;
        reg [7:0] r8, r9, r10, r11, r12, r13, r14, r15;
        begin
            s0 =state[127:120]; s1 =state[119:112];
            s2 =state[111:104]; s3 =state[103:96];
            s4 =state[95:88];   s5 =state[87:80];
            s6 =state[79:72];   s7 =state[71:64];
            s8 =state[63:56];   s9 =state[55:48];
            s10=state[47:40];   s11=state[39:32];
            s12=state[31:24];   s13=state[23:16];
            s14=state[15:8];    s15=state[7:0];

            // Column 0
            r0  = gf_mul2(s0)  ^ gf_mul3(s1)  ^ s2         ^ s3;
            r1  = s0           ^ gf_mul2(s1)  ^ gf_mul3(s2) ^ s3;
            r2  = s0           ^ s1           ^ gf_mul2(s2)  ^ gf_mul3(s3);
            r3  = gf_mul3(s0)  ^ s1           ^ s2          ^ gf_mul2(s3);
            // Column 1
            r4  = gf_mul2(s4)  ^ gf_mul3(s5)  ^ s6         ^ s7;
            r5  = s4           ^ gf_mul2(s5)  ^ gf_mul3(s6) ^ s7;
            r6  = s4           ^ s5           ^ gf_mul2(s6)  ^ gf_mul3(s7);
            r7  = gf_mul3(s4)  ^ s5           ^ s6          ^ gf_mul2(s7);
            // Column 2
            r8  = gf_mul2(s8)  ^ gf_mul3(s9)  ^ s10        ^ s11;
            r9  = s8           ^ gf_mul2(s9)  ^ gf_mul3(s10)^ s11;
            r10 = s8           ^ s9           ^ gf_mul2(s10) ^ gf_mul3(s11);
            r11 = gf_mul3(s8)  ^ s9           ^ s10         ^ gf_mul2(s11);
            // Column 3
            r12 = gf_mul2(s12) ^ gf_mul3(s13) ^ s14        ^ s15;
            r13 = s12          ^ gf_mul2(s13) ^ gf_mul3(s14)^ s15;
            r14 = s12          ^ s13          ^ gf_mul2(s14) ^ gf_mul3(s15);
            r15 = gf_mul3(s12) ^ s13          ^ s14         ^ gf_mul2(s15);

            mix_columns = {r0,r1,r2,r3,r4,r5,r6,r7,r8,r9,r10,r11,r12,r13,r14,r15};
        end
    endfunction

    // ================================================================
    // Key Expansion Round Constants (FIPS 197, Section 5.2)
    // ================================================================
    function [7:0] rcon;
        input [3:0] round;
        begin
            case (round)
                4'd1:  rcon = 8'h01;
                4'd2:  rcon = 8'h02;
                4'd3:  rcon = 8'h04;
                4'd4:  rcon = 8'h08;
                4'd5:  rcon = 8'h10;
                4'd6:  rcon = 8'h20;
                4'd7:  rcon = 8'h40;
                4'd8:  rcon = 8'h80;
                4'd9:  rcon = 8'h1b;
                4'd10: rcon = 8'h36;
                default: rcon = 8'h00;
            endcase
        end
    endfunction

    // ================================================================
    // Key Expansion: derive next round key from current round key
    // ================================================================
    function [127:0] next_round_key;
        input [127:0] prev_key;
        input [3:0] round;
        reg [31:0] w0, w1, w2, w3, temp;
        begin
            w0 = prev_key[127:96];
            w1 = prev_key[95:64];
            w2 = prev_key[63:32];
            w3 = prev_key[31:0];

            // RotWord + SubWord on last word of previous key
            temp = {sbox(w3[7:0]),   sbox(w3[31:24]), sbox(w3[23:16]), sbox(w3[15:8])};

            // XOR round constant into most significant byte
            temp[31:24] = temp[31:24] ^ rcon(round);

            w0 = w0 ^ temp;
            w1 = w1 ^ w0;
            w2 = w2 ^ w1;
            w3 = w3 ^ w2;

            next_round_key = {w0, w1, w2, w3};
        end
    endfunction

    // ================================================================
    // FSM Control
    // ================================================================
    localparam IDLE = 2'd0, ROUND = 2'd1, DONE_ST = 2'd2;

    reg [1:0]   fsm;
    reg [3:0]   round_cnt;
    reg [127:0] state_reg;
    reg [127:0] key_reg;

    always @(posedge clk) begin
        if (rst) begin
            fsm        <= IDLE;
            done       <= 1'b0;
            ciphertext <= 128'd0;
            round_cnt  <= 4'd0;
            state_reg  <= 128'd0;
            key_reg    <= 128'd0;
        end else begin
            case (fsm)
                IDLE: begin
                    done <= 1'b0;
                    if (start) begin
                        state_reg <= plaintext ^ key_in;   // Initial AddRoundKey
                        key_reg   <= key_in;
                        round_cnt <= 4'd1;
                        fsm       <= ROUND;
                    end
                end

                ROUND: begin
                    key_reg <= next_round_key(key_reg, round_cnt);

                    if (round_cnt < 4'd10) begin
                        // Rounds 1-9: SubBytes, ShiftRows, MixColumns, AddRoundKey
                        state_reg <= mix_columns(shift_rows(sub_bytes(state_reg)))
                                     ^ next_round_key(key_reg, round_cnt);
                        round_cnt <= round_cnt + 4'd1;
                    end else begin
                        // Round 10: SubBytes, ShiftRows, AddRoundKey (no MixColumns)
                        state_reg <= shift_rows(sub_bytes(state_reg))
                                     ^ next_round_key(key_reg, round_cnt);
                        fsm       <= DONE_ST;
                    end
                end

                DONE_ST: begin
                    ciphertext <= state_reg;
                    done       <= 1'b1;
                    fsm        <= IDLE;
                end

                default: fsm <= IDLE;
            endcase
        end
    end

endmodule
