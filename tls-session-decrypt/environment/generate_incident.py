#!/usr/bin/env python3
"""
Generate incident response data with standard and modified TLS 1.3 sessions.
4 sessions (2 standard, 2 modified key schedule), 6 leaked keys.

"""
import hashlib
import hmac as hmac_mod
import json
import os
import struct
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def hkdf_extract(salt, ikm):
    return hmac_mod.new(salt, ikm, hashlib.sha256).digest()

def hkdf_expand(prk, info, length):
    n = (length + 31) // 32
    okm, t = b"", b""
    for i in range(1, n + 1):
        t = hmac_mod.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]

def hkdf_expand_label(secret, label, context, length):
    tls_label = b"tls13 " + label.encode("ascii")
    hkdf_label = (
        struct.pack(">H", length)
        + struct.pack("B", len(tls_label))
        + tls_label
        + struct.pack("B", len(context))
        + context
    )
    return hkdf_expand(secret, hkdf_label, length)

def derive_secret(secret, label, messages):
    return hkdf_expand_label(secret, label, hashlib.sha256(messages).digest(), 32)

def make_nonce(iv, seq_num):
    seq_bytes = seq_num.to_bytes(12, "big")
    return bytes(a ^ b for a, b in zip(iv, seq_bytes))

def build_extension(ext_type, data):
    return struct.pack(">HH", ext_type, len(data)) + data


def compute_handshake_secret(shared_secret, use_standard=True):
    """Compute handshake_secret using standard or modified key schedule."""
    zeros = b"\x00" * 32
    if use_standard:
        early_secret = hkdf_extract(zeros, zeros)
        derived_1 = derive_secret(early_secret, "derived", b"")
        return hkdf_extract(derived_1, shared_secret)
    else:
        # Modified: skip early_secret derivation entirely
        return hkdf_extract(zeros, shared_secret)


def generate_session(client_priv_hex, server_priv_hex, client_random, server_random,
                     hostname, app_plaintexts, use_standard=True, corrupt_app_index=None):
    """Generate a complete encrypted session."""
    client_priv_bytes = bytes.fromhex(client_priv_hex)
    server_priv_bytes = bytes.fromhex(server_priv_hex)

    client_private = X25519PrivateKey.from_private_bytes(client_priv_bytes)
    server_private = X25519PrivateKey.from_private_bytes(server_priv_bytes)

    client_pub = client_private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    server_pub = server_private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    shared_secret = client_private.exchange(server_private.public_key())

    # === ClientHello ===
    sni_entry = b"\x00" + struct.pack(">H", len(hostname)) + hostname
    sni_list = struct.pack(">H", len(sni_entry)) + sni_entry
    sni_ext = build_extension(0x0000, sni_list)
    sv_ext = build_extension(0x002B, b"\x01\x03\x04")
    ks_entry = struct.pack(">HH", 0x001D, len(client_pub)) + client_pub
    ks_data = struct.pack(">H", len(ks_entry)) + ks_entry
    ks_ext = build_extension(0x0033, ks_data)

    extensions = sni_ext + sv_ext + ks_ext
    ch_body = (
        b"\x03\x03" + client_random + b"\x00"
        + b"\x00\x02\x13\x01" + b"\x01\x00"
        + struct.pack(">H", len(extensions)) + extensions
    )
    client_hello = b"\x01" + struct.pack(">I", len(ch_body))[1:] + ch_body

    # === ServerHello ===
    sv_ext_srv = build_extension(0x002B, b"\x03\x04")
    ks_srv_data = struct.pack(">HH", 0x001D, len(server_pub)) + server_pub
    ks_ext_srv = build_extension(0x0033, ks_srv_data)
    sh_extensions = sv_ext_srv + ks_ext_srv
    sh_body = (
        b"\x03\x03" + server_random + b"\x00"
        + b"\x13\x01" + b"\x00"
        + struct.pack(">H", len(sh_extensions)) + sh_extensions
    )
    server_hello = b"\x02" + struct.pack(">I", len(sh_body))[1:] + sh_body

    # === Key Schedule ===
    handshake_secret = compute_handshake_secret(shared_secret, use_standard=use_standard)

    transcript_ch_sh = client_hello + server_hello
    s_hs_traffic = derive_secret(handshake_secret, "s hs traffic", transcript_ch_sh)
    s_hs_key = hkdf_expand_label(s_hs_traffic, "key", b"", 16)
    s_hs_iv = hkdf_expand_label(s_hs_traffic, "iv", b"", 12)

    # === Server Handshake Plaintext ===
    ee = b"\x08\x00\x00\x02\x00\x00"
    cert_data = b"CN=" + hostname + b";O=TestCorp;SN=1"
    cert_entry = struct.pack(">I", len(cert_data))[1:] + cert_data + b"\x00\x00"
    cert_list = struct.pack(">I", len(cert_entry))[1:] + cert_entry
    cert_body = b"\x00" + cert_list
    certificate = b"\x0b" + struct.pack(">I", len(cert_body))[1:] + cert_body
    sig = hashlib.sha256(b"cv_" + hostname).digest()
    cv_body = b"\x08\x04" + struct.pack(">H", len(sig)) + sig
    cert_verify = b"\x0f" + struct.pack(">I", len(cv_body))[1:] + cv_body
    fin_data = hashlib.sha256(b"fin_" + hostname).digest()
    finished = b"\x14" + struct.pack(">I", len(fin_data))[1:] + fin_data

    server_hs_plaintext = ee + certificate + cert_verify + finished

    # === Encrypt handshake ===
    inner_hs = server_hs_plaintext + b"\x16"
    hs_aad = b"\x17\x03\x03" + struct.pack(">H", len(inner_hs) + 16)
    aesgcm_hs = AESGCM(s_hs_key)
    nonce_hs = make_nonce(s_hs_iv, 0)
    encrypted_hs = aesgcm_hs.encrypt(nonce_hs, inner_hs, hs_aad)

    encrypted_records = []
    hs_record = hs_aad + encrypted_hs
    encrypted_records.append(hs_record.hex())

    # === Application keys ===
    transcript_full = client_hello + server_hello + server_hs_plaintext
    derived_2 = derive_secret(handshake_secret, "derived", b"")
    master_secret = hkdf_extract(derived_2, b"\x00" * 32)
    s_ap_traffic = derive_secret(master_secret, "s ap traffic", transcript_full)
    s_ap_key = hkdf_expand_label(s_ap_traffic, "key", b"", 16)
    s_ap_iv = hkdf_expand_label(s_ap_traffic, "iv", b"", 12)

    # === Encrypt application data ===
    aesgcm_app = AESGCM(s_ap_key)
    for i, pt in enumerate(app_plaintexts):
        inner = pt + b"\x17"
        app_aad = b"\x17\x03\x03" + struct.pack(">H", len(inner) + 16)
        nonce = make_nonce(s_ap_iv, i)
        ct = aesgcm_app.encrypt(nonce, inner, app_aad)

        if corrupt_app_index is not None and i == corrupt_app_index:
            ct_arr = bytearray(ct)
            ct_arr[len(ct_arr) // 2] ^= 0xFF
            ct = bytes(ct_arr)

        app_record = app_aad + ct
        encrypted_records.append(app_record.hex())

    return {
        "client_hello": client_hello.hex(),
        "server_hello": server_hello.hex(),
        "encrypted_records": encrypted_records,
    }


def main():
    # Client private keys (go in leaked_keys.json)
    client_keys = {
        "key_1": "a1a2a3a4a5a6a7a8a9aaabacadaeafb0b1b2b3b4b5b6b7b8b9babbbcbdbebfc0",
        "key_2": "c1c2c3c4c5c6c7c8c9cacbcccdcecfd0d1d2d3d4d5d6d7d8d9dadbdcdddedfe0",
        "key_3": "b0b1b2b3b4b5b6b7b8b9babbbcbdbebfc0c1c2c3c4c5c6c7c8c9cacbcccdcecf",
        "key_4": "e0e1e2e3e4e5e6e7e8e9eaebecedeeeff0f1f2f3f4f5f6f7f8f9fafbfcfdfeff",
        "key_5": "0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20",
        "key_6": "3031323334353637383940414243444546474849505152535455565758596061",
    }

    # Server private keys (NOT leaked) — alpha and delta share the same server
    server_keys = {
        "alpha": "d0d1d2d3d4d5d6d7d8d9dadbdcdddedfe0e1e2e3e4e5e6e7e8e9eaebecedeeef",
        "beta":  "f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff0102030405060708090a0b0c0d0e0f10",
        "gamma": "2021222324252627282930313233343536373839404142434445464748495051",
        "delta": "d0d1d2d3d4d5d6d7d8d9dadbdcdddedfe0e1e2e3e4e5e6e7e8e9eaebecedeeef",
    }

    # Session -> client key mapping (the solver must discover this)
    session_key_map = {
        "alpha": "key_3",
        "beta":  "key_1",
        "gamma": "key_4",
        "delta": "key_6",
    }

    # Which sessions use standard vs modified TLS
    session_standard = {
        "alpha": True,
        "beta":  True,
        "gamma": False,
        "delta": False,
    }

    randoms = {
        "alpha": (bytes.fromhex("aa" * 32), bytes.fromhex("11" * 32)),
        "beta":  (bytes.fromhex("bb" * 32), bytes.fromhex("22" * 32)),
        "gamma": (bytes.fromhex("cc" * 32), bytes.fromhex("33" * 32)),
        "delta": (bytes.fromhex("dd" * 32), bytes.fromhex("44" * 32)),
    }

    hostnames = {
        "alpha": b"api.internal.corp",
        "beta":  b"intranet.corp",
        "gamma": b"data-export.corp",
        "delta": b"api.internal.corp",
    }

    app_data = {
        "alpha": [
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nX-Request-ID: a847f\r\n\r\n",
            b'{"database":{"host":"db-prod-master.internal","port":5432,"user":"admin","pass":"Kj8#mP2$vL9nQ4wR"},"api_keys":{"stripe":"sk_live_4eC39HqLyjWDarjtT1zdp7dc","aws":"AKIAIOSFODNN7EXAMPLE"}}',
        ],
        "beta": [
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n",
            b"<html><head><title>Intranet</title></head><body><h1>Welcome</h1><p>Q4 planning meeting moved to Friday 3pm. Lunch will be provided.</p></body></html>",
        ],
        "gamma": [
            b"HTTP/1.1 200 OK\r\nContent-Type: text/csv\r\nX-Export: customer-db\r\n\r\n",
            b"name,email,ssn,account_number\n",
            b"Jane Doe,jane.doe@email.com,987-65-4321,ACC-7742\n",
            b"John Smith,john.smith@corp.net,123-45-6789,ACC-0019\nAlice Brown,alice.b@mail.org,456-78-9012,ACC-3351\n",
        ],
        "delta": [
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nX-Internal: arch-review\r\n\r\n",
            b"=== INTERNAL ARCHITECTURE REVIEW ===\n\nService Mesh: Istio 1.19 on k8s 1.28\n",
            b"Auth: OAuth2 + mTLS between services\nSecrets: HashiCorp Vault (auto-unseal via AWS KMS)\n",
            b"DB: PostgreSQL 16 primary-replica, pgbouncer connection pooling\nFirewall rules: allow 10.0.0.0/8 ingress, deny all egress except 443\n",
        ],
    }

    sessions = []
    for sid in ["alpha", "beta", "gamma", "delta"]:
        key_id = session_key_map[sid]
        corrupt_idx = 2 if sid == "gamma" else None

        session = generate_session(
            client_keys[key_id], server_keys[sid],
            randoms[sid][0], randoms[sid][1],
            hostnames[sid], app_data[sid],
            use_standard=session_standard[sid],
            corrupt_app_index=corrupt_idx,
        )
        session["id"] = sid
        sessions.append(session)

    os.makedirs("/app/incident", exist_ok=True)

    with open("/app/incident/captures.json", "w") as f:
        json.dump({"sessions": sessions}, f, indent=2)

    leaked_keys = [
        {"id": kid, "private_key_hex": client_keys[kid]}
        for kid in ["key_3", "key_5", "key_1", "key_4", "key_6", "key_2"]
    ]
    with open("/app/incident/leaked_keys.json", "w") as f:
        json.dump(leaked_keys, f, indent=2)

    with open("/app/incident/context.txt", "w") as f:
        f.write(
            "Incident #IR-2024-0847\n\n"
            "Timeline: Suspicious outbound connections detected from web-app-prod-03\n"
            "(10.0.1.42) to four external IPs over port 443 on 2024-11-15 between\n"
            "03:41 and 03:52 UTC.\n\n"
            "Response team captured session data from the network tap before the\n"
            "connections terminated. Six private keys were found in /tmp/.cache on\n"
            "the compromised host.\n\n"
            "MALWARE ANALYSIS (partial):\n"
            "The malware binary recovered from the compromised host was partially\n"
            "reverse-engineered. It uses a TLS 1.3-like encrypted channel but with\n"
            "a MODIFIED key schedule. Static analysis of the crypto routines shows\n"
            "that for some sessions, the malware SKIPS the early_secret derivation\n"
            "step entirely:\n\n"
            "  Standard TLS 1.3:\n"
            "    early_secret = HKDF-Extract(salt=zeros(32), ikm=zeros(32))\n"
            "    derived = Derive-Secret(early_secret, 'derived', '')\n"
            "    handshake_secret = HKDF-Extract(salt=derived, ikm=shared_secret)\n\n"
            "  Malware variant:\n"
            "    handshake_secret = HKDF-Extract(salt=zeros(32), ikm=shared_secret)\n\n"
            "All other key derivation steps after handshake_secret follow standard\n"
            "TLS 1.3 (RFC 8446 Section 7.1). The sessions using the standard vs.\n"
            "modified key schedule are NOT labeled in the captures. You must determine\n"
            "which variant each session uses through trial decryption.\n\n"
            "ADDITIONAL NOTE: Some captures may have been partially corrupted during\n"
            "collection. At least one session may have corrupted encrypted records.\n\n"
            "Priority: Determine what data was exfiltrated, assess the security\n"
            "implications of the modified protocol, and identify any infrastructure\n"
            "reuse across sessions.\n"
        )

    print("Incident data generated successfully.")
    for s in sessions:
        print(f"  Session {s['id']}: {len(s['encrypted_records'])} encrypted records, "
              f"standard={session_standard[s['id']]}")


if __name__ == "__main__":
    main()
