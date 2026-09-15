`timescale 1ns/1ps
//
// AES-128 Decryption Module
// Implement the FIPS 197 Inverse Cipher (Section 5.3)

module aes128_decrypt(
    input              clk,
    input              rst,
    input              start,
    input      [127:0] ciphertext,
    input      [127:0] key_in,
    output reg [127:0] plaintext,
    output reg         done
);

    // TODO: Implement the FIPS 197 Inverse Cipher
    //
    // The inverse operations InvSubBytes, InvShiftRows, and InvMixColumns
    // reverse their forward counterparts. AddRoundKey is self-inverse.
    // Round keys must be applied in reverse order (10 down to 0).
    //
    // See aes128_encrypt.v for the forward S-box, key expansion logic,
    // and module structure.

    always @(posedge clk) begin
        if (rst) begin
            plaintext <= 128'd0;
            done      <= 1'b0;
        end else begin
            done <= 1'b0;
        end
    end

endmodule
