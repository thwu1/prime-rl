#!/usr/bin/env python3
"""Generate encrypted configuration data for dual-config malware sample."""

def xor_encrypt(data, key):
    return bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])

def rc4_crypt(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) & 0xFF
        S[i], S[j] = S[j], S[i]
    result = bytearray(len(data))
    i = j = 0
    for k in range(len(data)):
        i = (i + 1) & 0xFF
        j = (j + S[i]) & 0xFF
        S[i], S[j] = S[j], S[i]
        result[k] = data[k] ^ S[(S[i] + S[j]) & 0xFF]
    return bytes(result)

def to_c_array(name, data):
    hex_vals = ", ".join(f"0x{b:02x}" for b in data)
    return f"const unsigned char {name}[] = {{{hex_vals}}};\n#define {name.upper()}_LEN {len(data)}"

# Config A (real operational config)
XOR_KEY_A = bytes([0xa7, 0xb3, 0xc1, 0xd9])
RC4_KEY_A = b"Operator"

config_a = b"\n".join([
    b"c2_primary=update-service.darkcloud.network",
    b"c2_secondary=cdn-static.shadownet.io",
    b"campaign_id=ECHO-7391-KAPPA",
    b"mutex=Global\\{8F14E45F-CEEA-4E3F-A3B0-4BE6B2626E33}",
    b"exfil_port=8443",
    b"persistence=/etc/cron.d/system-update",
]) + b"\n"

# Config B (analyst trap config)
XOR_KEY_B = bytes([0xd2, 0xe5, 0xf8, 0x91])
RC4_KEY_B = b"SvcAdmin"

config_b = b"\n".join([
    b"c2_primary=api-gateway.stormfront.xyz",
    b"c2_secondary=backup-relay.stormfront.xyz",
    b"campaign_id=PHANTOM-2048-SIGMA",
    b"mutex=Global\\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}",
    b"exfil_port=9443",
    b"persistence=/etc/systemd/system/svchost.service",
]) + b"\n"

enc_rc4_key_a = xor_encrypt(RC4_KEY_A, XOR_KEY_A)
enc_config_a = rc4_crypt(RC4_KEY_A, config_a)

enc_rc4_key_b = xor_encrypt(RC4_KEY_B, XOR_KEY_B)
enc_config_b = rc4_crypt(RC4_KEY_B, config_b)

with open("encrypted_data.h", "w") as f:
    f.write("#ifndef ENCRYPTED_DATA_H\n#define ENCRYPTED_DATA_H\n\n")
    f.write("/* Config block A */\n")
    f.write(to_c_array("xor_key_a", XOR_KEY_A) + "\n\n")
    f.write(to_c_array("rc4_key_enc_a", enc_rc4_key_a) + "\n\n")
    f.write(to_c_array("config_enc_a", enc_config_a) + "\n\n")
    f.write("/* Config block B */\n")
    f.write(to_c_array("xor_key_b", XOR_KEY_B) + "\n\n")
    f.write(to_c_array("rc4_key_enc_b", enc_rc4_key_b) + "\n\n")
    f.write(to_c_array("config_enc_b", enc_config_b) + "\n\n")
    f.write("#endif\n")

print(f"Config A: {len(enc_config_a)} bytes encrypted")
print(f"Config B: {len(enc_config_b)} bytes encrypted")
