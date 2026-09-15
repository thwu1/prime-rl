#!/usr/bin/env python3
"""
Decrypt firmware by exploiting AES-OFB IV reuse.

The encryption tool (encrypt_firmware.py) generates a keystream via iterated
AES-ECB on a running state (= OFB mode) and XORs each chunk with it.
Because every chunk uses the same key and IV, the keystream is identical
across all chunks.

Attack:
  keystream = known_plaintext XOR known_ciphertext
  plaintext_i = ciphertext_i XOR keystream

No AES key or library is needed — pure XOR suffices.
"""
import json
import os
import re
import tarfile


def xor_bytes(a, b):
    """XOR two byte strings of equal length."""
    return bytes(x ^ y for x, y in zip(a, b))


def main():
    os.chdir("/app")

    # Step 1: Unpack outer archive
    print("[*] Unpacking outer archive...")
    with tarfile.open("firmware_update.tar.gz", "r:gz") as tar:
        tar.extractall(".")

    # Step 2: Unpack inner archive
    print("[*] Unpacking inner archive...")
    with tarfile.open("ivi_firmware.tar.gz", "r:gz") as tar:
        tar.extractall(".")

    # Step 3: Read metadata
    with open("ivi_firmware/metadata.json") as f:
        meta = json.load(f)

    chunk_size = meta["chunk_size"]
    total_chunks = meta["total_chunks"]
    verify_idx = meta["verification_chunk_index"]

    print(f"[*] Firmware: {total_chunks} chunks of {chunk_size} bytes")
    print(f"[*] Known plaintext chunk: {verify_idx}")

    enc_dir = "ivi_firmware/encrypted"

    # Step 4: Recover keystream using known-plaintext attack
    #   keystream = plaintext XOR ciphertext
    with open(os.path.join(enc_dir, f"verify_chunk_{verify_idx:04d}.bin"), "rb") as f:
        known_plain = f.read()

    with open(os.path.join(enc_dir, f"chunk_{verify_idx:04d}.enc"), "rb") as f:
        known_cipher = f.read()

    keystream = xor_bytes(known_plain, known_cipher)
    print(f"[*] Recovered {len(keystream)}-byte keystream")

    # Step 5: Decrypt all chunks
    firmware = b""
    for i in range(total_chunks):
        with open(os.path.join(enc_dir, f"chunk_{i:04d}.enc"), "rb") as f:
            enc_chunk = f.read()
        plain_chunk = xor_bytes(enc_chunk, keystream)
        firmware += plain_chunk

    # Step 6: Write decrypted firmware
    with open("decrypted_firmware.bin", "wb") as f:
        f.write(firmware)
    print(f"[*] Wrote decrypted firmware ({len(firmware)} bytes)")

    # Step 7: Extract flag
    match = re.search(rb"FLAG\{[^}]+\}", firmware)
    if match:
        flag = match.group(0).decode()
        with open("flag.txt", "w") as f:
            f.write(flag)
        print(f"[+] Flag: {flag}")
    else:
        print("[-] No flag found in decrypted firmware!")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
