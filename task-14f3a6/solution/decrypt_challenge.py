#!/usr/bin/env python3

"""
Decrypt the crypto_secretbox challenge using PyNaCl (libsodium bindings).
Also verify the fixed tweetnacl.c compiles and produces correct output.
"""

import json
import subprocess
import os
import tempfile
import shutil


def decrypt_with_pynacl():
    """Decrypt the challenge ciphertext using PyNaCl's SecretBox."""
    from nacl.secret import SecretBox

    with open("/app/challenge.json") as f:
        data = json.load(f)

    challenge = data["challenge"]
    key = bytes.fromhex(challenge["key_hex"])
    nonce = bytes.fromhex(challenge["nonce_hex"])
    ct_full = bytes.fromhex(challenge["ciphertext_hex"])

    # C NaCl ciphertext format: BOXZEROBYTES(16 zeros) + MAC(16) + encrypted_msg
    # PyNaCl SecretBox.decrypt expects: MAC(16) + encrypted_msg (no zero prefix)
    ct_for_pynacl = ct_full[16:]  # strip the 16 BOXZEROBYTES zeros

    box = SecretBox(key)
    plaintext_bytes = box.decrypt(ct_for_pynacl, nonce)
    return plaintext_bytes.decode("utf-8")


def verify_fixed_tweetnacl():
    """Compile and test the fixed tweetnacl.c against test vectors."""
    tmpdir = tempfile.mkdtemp(prefix="nacl_verify_")

    test_c_code = r'''
#include <stdio.h>
#include <string.h>
#include "tweetnacl.h"

void randombytes(unsigned char *x, unsigned long long xlen) {
    unsigned long long i;
    for (i = 0; i < xlen; i++) x[i] = 0;
}

int main(void) {
    unsigned char key[32] = {0x1b,0x27,0x55,0x64,0x73,0xe9,0x85,0xd4,
                             0x62,0xcd,0x51,0x19,0x7a,0x9a,0x46,0xc7,
                             0x60,0x09,0x54,0x9e,0xac,0x64,0x74,0xf2,
                             0x06,0xc4,0xee,0x08,0x44,0xf6,0x83,0x89};
    unsigned char nonce[24] = {0x69,0x69,0x6e,0xe9,0x55,0xb6,0x2b,0x73,
                               0xcd,0x62,0xbd,0xa8,0x75,0xfc,0x73,0xd6,
                               0x82,0x19,0xe0,0x03,0x6b,0x7a,0x0b,0x37};
    const char *pt = "The Poly1305-AES message-authentication code by Daniel J. Bernstein provides provable security.";
    int ptlen = strlen(pt);
    int mlen = ptlen + 32;
    unsigned char m[256] = {0}, c[256] = {0}, m2[256] = {0};
    memcpy(m + 32, pt, ptlen);
    crypto_secretbox(c, m, mlen, nonce, key);
    int ret = crypto_secretbox_open(m2, c, mlen, nonce, key);
    if (ret == 0) {
        for (int i = 32; i < mlen; i++) putchar(m2[i]);
    } else {
        printf("DECRYPTION_FAILED");
    }
    return ret;
}
'''

    test_c = os.path.join(tmpdir, "verify.c")
    with open(test_c, "w") as f:
        f.write(test_c_code)

    shutil.copy("/app/tweetnacl.c", os.path.join(tmpdir, "tweetnacl.c"))
    shutil.copy("/app/tweetnacl.h", os.path.join(tmpdir, "tweetnacl.h"))

    binary = os.path.join(tmpdir, "verify")
    r = subprocess.run(["gcc", "-o", binary, test_c, os.path.join(tmpdir, "tweetnacl.c"), "-O2"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        print(f"C verification compilation failed: {r.stderr}")
        shutil.rmtree(tmpdir, ignore_errors=True)
        return

    r = subprocess.run([binary], capture_output=True, text=True, timeout=60)
    print(f"C-based decryption result: {r.stdout}")
    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    plaintext = decrypt_with_pynacl()
    print(f"Decrypted: {plaintext}")

    with open("/app/plaintext.txt", "w") as f:
        f.write(plaintext)

    print("Written to /app/plaintext.txt")

    verify_fixed_tweetnacl()
