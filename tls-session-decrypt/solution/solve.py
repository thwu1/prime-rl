#!/usr/bin/env python3
"""
Solution: Encrypted session recovery with dual-mode TLS 1.3 key schedule,
protocol variant detection, shared infrastructure analysis, and vulnerability assessment.

"""
import hashlib
import hmac as hmac_mod
import json
import os
import struct

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# === HKDF / TLS 1.3 key schedule ===

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
        + struct.pack("B", len(tls_label)) + tls_label
        + struct.pack("B", len(context)) + context
    )
    return hkdf_expand(secret, hkdf_label, length)

def derive_secret(secret, label, messages):
    return hkdf_expand_label(secret, label, hashlib.sha256(messages).digest(), 32)

def make_nonce(iv, seq):
    return bytes(a ^ b for a, b in zip(iv, seq.to_bytes(12, "big")))


# === Protocol parsing ===

def parse_server_pubkey(sh):
    """Extract server's X25519 public key from ServerHello key_share extension."""
    off = 4  # type(1) + length(3)
    off += 2  # version
    off += 32  # random
    sid_len = sh[off]
    off += 1 + sid_len  # session_id length + session_id
    off += 2  # cipher_suite
    off += 1  # compression
    ext_len = struct.unpack(">H", sh[off:off + 2])[0]
    off += 2
    end = off + ext_len
    while off < end:
        et = struct.unpack(">H", sh[off:off + 2])[0]
        el = struct.unpack(">H", sh[off + 2:off + 4])[0]
        if et == 0x0033:  # key_share
            kl = struct.unpack(">H", sh[off + 6:off + 8])[0]
            return sh[off + 8:off + 8 + kl]
        off += 4 + el
    raise ValueError("No key_share extension found in ServerHello")


def compute_handshake_secret(shared_secret, use_standard):
    """Compute handshake_secret via standard or modified key schedule."""
    zeros = b"\x00" * 32
    if use_standard:
        early_secret = hkdf_extract(zeros, zeros)
        derived_1 = derive_secret(early_secret, "derived", b"")
        return hkdf_extract(derived_1, shared_secret)
    else:
        # Modified: skip early_secret, derive directly
        return hkdf_extract(zeros, shared_secret)


# === Session decryption ===

def attempt_decrypt(session, priv_hex, use_standard):
    """Try decrypting a session with a candidate key and key schedule variant.
    Returns dict with text, has_loss, variant if successful, None otherwise."""
    ch = bytes.fromhex(session["client_hello"])
    sh = bytes.fromhex(session["server_hello"])

    try:
        spub = parse_server_pubkey(sh)
        cpk = X25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
        shared = cpk.exchange(X25519PublicKey.from_public_bytes(spub))
    except Exception:
        return None

    handshake_secret = compute_handshake_secret(shared, use_standard)

    # Handshake traffic keys
    tr = ch + sh
    s_hs_t = derive_secret(handshake_secret, "s hs traffic", tr)
    s_hs_k = hkdf_expand_label(s_hs_t, "key", b"", 16)
    s_hs_iv = hkdf_expand_label(s_hs_t, "iv", b"", 12)

    # Try decrypting first encrypted record (server handshake)
    rec0 = bytes.fromhex(session["encrypted_records"][0])
    aad0, ct0 = rec0[:5], rec0[5:]
    try:
        inner = AESGCM(s_hs_k).decrypt(make_nonce(s_hs_iv, 0), ct0, aad0)
    except Exception:
        return None  # Wrong key or wrong variant

    hs_pt = inner[:-1]  # strip inner content type

    # Application traffic keys
    tr_full = ch + sh + hs_pt
    d2 = derive_secret(handshake_secret, "derived", b"")
    ms = hkdf_extract(d2, b"\x00" * 32)
    s_ap_t = derive_secret(ms, "s ap traffic", tr_full)
    s_ap_k = hkdf_expand_label(s_ap_t, "key", b"", 16)
    s_ap_iv = hkdf_expand_label(s_ap_t, "iv", b"", 12)

    # Decrypt application records, handling corruption
    aesgcm = AESGCM(s_ap_k)
    parts = []
    has_loss = False
    for i, rh in enumerate(session["encrypted_records"][1:]):
        r = bytes.fromhex(rh)
        aad, ct = r[:5], r[5:]
        try:
            dec = aesgcm.decrypt(make_nonce(s_ap_iv, i), ct, aad)
            parts.append(dec[:-1])
        except Exception:
            has_loss = True
            parts.append(None)

    text = b"".join(p for p in parts if p is not None).decode("utf-8", errors="replace")
    variant = "standard" if use_standard else "modified"
    return {"text": text, "has_loss": has_loss, "variant": variant}


def classify_content(text):
    """Classify content by category and severity."""
    text_lower = text.lower()

    # Check for credentials (API keys, passwords, access keys)
    credential_indicators = ["sk_live_", "akia", '"pass":', "api_key", "private_key"]
    for ind in credential_indicators:
        if ind.lower() in text_lower:
            return "credentials", "critical"

    # Check for PII (SSNs, account numbers with personal data)
    pii_indicators = ["ssn", "social security", "account_number"]
    for ind in pii_indicators:
        if ind in text_lower:
            return "pii", "high"

    # Check for internal documentation
    internal_indicators = ["internal architecture", "firewall rules", "service mesh",
                           "vault", "infrastructure"]
    for ind in internal_indicators:
        if ind.lower() in text_lower:
            return "internal_docs", "medium"

    return "public_info", "low"


def find_shared_servers(captures):
    """Identify sessions that share the same server public key."""
    server_pubkeys = {}
    for session in captures["sessions"]:
        sh = bytes.fromhex(session["server_hello"])
        spub = parse_server_pubkey(sh).hex()
        if spub not in server_pubkeys:
            server_pubkeys[spub] = []
        server_pubkeys[spub].append(session["id"])

    shared = []
    for spub, sids in server_pubkeys.items():
        if len(sids) > 1:
            shared = sorted(sids)
    return shared


def main():
    with open("/app/incident/captures.json") as f:
        captures = json.load(f)
    with open("/app/incident/leaked_keys.json") as f:
        keys = json.load(f)

    os.makedirs("/app/output/decrypted", exist_ok=True)

    key_mapping = {}
    decrypted_texts = {}
    session_info = {}

    for session in captures["sessions"]:
        sid = session["id"]
        print(f"\nAnalyzing session {sid}...")
        found = False
        for kentry in keys:
            # Try standard TLS 1.3 first, then modified
            for use_std in [True, False]:
                result = attempt_decrypt(session, kentry["private_key_hex"], use_std)
                if result is not None:
                    key_mapping[sid] = kentry["id"]
                    decrypted_texts[sid] = result["text"]
                    session_info[sid] = {
                        "variant": result["variant"],
                        "has_loss": result["has_loss"],
                    }
                    with open(f"/app/output/decrypted/{sid}.txt", "w") as f:
                        f.write(result["text"])
                    variant_str = "standard" if use_std else "modified"
                    print(f"  Decrypted with {kentry['id']} ({variant_str}), "
                          f"{len(result['text'])} chars")
                    found = True
                    break
            if found:
                break
        if not found:
            print(f"  No matching key found")

    # Write key mapping
    with open("/app/output/key_mapping.json", "w") as f:
        json.dump(key_mapping, f, indent=2)

    # Classify and write exfiltration report
    exfiltrated = []
    benign = []
    session_assessments = {}

    for sid in sorted(decrypted_texts):
        category, severity = classify_content(decrypted_texts[sid])
        info = session_info[sid]

        assessment = {
            "protocol_variant": info["variant"],
            "content_category": category,
            "severity": severity,
        }
        if info["has_loss"]:
            assessment["data_loss"] = True

        session_assessments[sid] = assessment

        if category in ("credentials", "pii", "internal_docs"):
            exfiltrated.append(sid)
        else:
            benign.append(sid)

    exfil_report = {
        "exfiltrated_sessions": sorted(exfiltrated),
        "benign_sessions": sorted(benign),
    }
    with open("/app/output/exfiltration_report.json", "w") as f:
        json.dump(exfil_report, f, indent=2)

    # Find shared server infrastructure
    shared_servers = find_shared_servers(captures)

    # Determine incident priority (by severity)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    priority = sorted(
        session_assessments.keys(),
        key=lambda s: severity_order.get(session_assessments[s]["severity"], 99)
    )

    # Write vulnerability assessment
    vuln_assessment = {
        "sessions": session_assessments,
        "shared_server_sessions": shared_servers,
        "incident_priority": priority,
    }
    with open("/app/output/vulnerability_assessment.json", "w") as f:
        json.dump(vuln_assessment, f, indent=2)

    print(f"\nResults:")
    print(f"  Exfiltrated: {sorted(exfiltrated)}")
    print(f"  Benign: {sorted(benign)}")
    print(f"  Shared servers: {shared_servers}")
    print(f"  Priority: {priority}")


if __name__ == "__main__":
    main()
