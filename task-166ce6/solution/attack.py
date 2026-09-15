"""
Poly1305 implementation audit and nonce-reuse forgery attack.

Identifies the server's implementation variant among three candidates,
discovers deviations from RFC 8439, analyzes captured traffic for
exploitable weaknesses, and forges a valid authenticator for the
target message.
"""

import json
import subprocess
import sys

P = (1 << 130) - 5


def le_bytes_to_int(b: bytes) -> int:
    return int.from_bytes(b, "little")


def be_bytes_to_int(b: bytes) -> int:
    return int.from_bytes(b, "big")


def int_to_le_bytes(n: int, length: int) -> bytes:
    return (n % (1 << (8 * length))).to_bytes(length, "little")


def run_impl(name: str, r_hex: str, s_hex: str, msg_hex: str) -> str:
    """Run a compiled Poly1305 implementation and return the hex tag."""
    binary = f"/app/implementations/{name}"
    result = subprocess.run(
        [binary, r_hex, s_hex, msg_hex],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        raise RuntimeError(f"{name} failed: {result.stderr}")
    return result.stdout.strip()


def is_clamped(r_int: int) -> bool:
    """Check Poly1305 clamping constraints on r."""
    r_bytes = int_to_le_bytes(r_int, 16)
    for i in [3, 7, 11, 15]:
        if r_bytes[i] & 0xF0:
            return False
    for i in [4, 8, 12]:
        if r_bytes[i] & 0x03:
            return False
    return True


def mod_inverse(a: int, m: int) -> int:
    """Modular inverse via Fermat's little theorem (m is prime)."""
    return pow(a, m - 2, m)


def main():
    # Load data files
    with open("/app/test_vectors.json") as f:
        test_vectors = json.load(f)
    with open("/app/server_traffic.json") as f:
        traffic = json.load(f)
    with open("/app/target.json") as f:
        target = json.load(f)

    # Load Python reference for comparison
    sys.path.insert(0, "/app")
    from poly1305_ref import poly1305 as ref_poly1305

    print("=" * 60)
    print("STEP 1: Test all implementations against RFC 8439 vectors")
    print("=" * 60)

    impl_names = ["alpha", "beta", "gamma"]
    impl_results = {name: {"pass": 0, "fail": 0} for name in impl_names}

    for tv in test_vectors:
        r_hex = tv["r_hex"]
        s_hex = tv["s_hex"]
        msg_hex = tv["message_hex"]
        expected_hex = tv["expected_tag_hex"]

        ref_tag = ref_poly1305(
            bytes.fromhex(msg_hex),
            bytes.fromhex(r_hex),
            bytes.fromhex(s_hex)
        ).hex()
        print(f"\n  Vector: {tv['description']}")
        print(f"    Reference (Python): {ref_tag}")
        assert ref_tag == expected_hex, f"Python reference mismatch!"

        for name in impl_names:
            tag = run_impl(name, r_hex, s_hex, msg_hex)
            match = tag == expected_hex
            impl_results[name]["pass" if match else "fail"] += 1
            print(f"    {name}: {tag} {'PASS' if match else 'FAIL'}")

    print("\n  Summary:")
    for name in impl_names:
        r = impl_results[name]
        print(f"    {name}: {r['pass']} pass, {r['fail']} fail")

    # Determine which implementations deviate
    deviating = [n for n in impl_names if impl_results[n]["fail"] > 0]
    standard = [n for n in impl_names if impl_results[n]["fail"] == 0]
    print(f"\n  Standard-compliant: {standard}")
    print(f"  Deviating: {deviating}")

    print("\n" + "=" * 60)
    print("STEP 2: Analyze traffic for exploitable weaknesses")
    print("=" * 60)

    # Look for nonce reuse in captured traffic
    nonce_groups = {}
    for entry in traffic:
        nonce = entry["nonce_hex"]
        nonce_groups.setdefault(nonce, []).append(entry)

    reused_nonce = None
    reused_entries = None
    for nonce, entries in nonce_groups.items():
        if len(entries) >= 2:
            reused_nonce = nonce
            reused_entries = entries
            break

    if reused_nonce is None:
        print("ERROR: No exploitable weakness found in traffic!")
        sys.exit(1)

    affected_seqs = sorted([e["seq"] for e in reused_entries])
    print(f"\n  Found nonce reuse: {reused_nonce}")
    print(f"  Affected sequences: {affected_seqs}")

    e1, e2 = reused_entries[0], reused_entries[1]
    msg1 = bytes.fromhex(e1["message_hex"])
    msg2 = bytes.fromhex(e2["message_hex"])
    tag1_int = le_bytes_to_int(bytes.fromhex(e1["authenticator_hex"]))
    tag2_int = le_bytes_to_int(bytes.fromhex(e2["authenticator_hex"]))

    assert len(msg1) <= 16 and len(msg2) <= 16, \
        "Attack requires single-block messages for the reused-nonce pair"

    print("\n" + "=" * 60)
    print("STEP 3: Identify server implementation via algebraic recovery")
    print("=" * 60)

    # Define encoding functions for each variant
    def encode_le_sentinel(msg):
        return le_bytes_to_int(msg) + (1 << (8 * len(msg)))

    def encode_be_sentinel(msg):
        return be_bytes_to_int(msg) + (1 << (8 * len(msg)))

    def encode_le_no_sentinel(msg):
        return le_bytes_to_int(msg)

    encoders = {
        "alpha": encode_le_sentinel,
        "beta": encode_be_sentinel,
        "gamma": encode_le_no_sentinel,
    }

    matching_impl = None
    recovered_r = None
    recovered_s = None

    for impl_name, encoder in encoders.items():
        c1 = encoder(msg1)
        c2 = encoder(msg2)
        diff_c = (c1 - c2) % P
        diff_tag = (tag1_int - tag2_int) % (1 << 128)

        if diff_c == 0:
            print(f"\n  {impl_name}: diff_c = 0, cannot solve")
            continue

        inv_diff_c = mod_inverse(diff_c, P)

        found = False
        for k in range(-4, 5):
            candidate = ((diff_tag + k * (1 << 128)) % P * inv_diff_c) % P
            if candidate < (1 << 128) and is_clamped(candidate):
                h1 = (c1 * candidate) % P
                s_candidate = (tag1_int - h1) % (1 << 128)

                h2 = (c2 * candidate) % P
                tag2_check = (h2 + s_candidate) % (1 << 128)
                if tag2_check == tag2_int:
                    print(f"\n  {impl_name}: FOUND valid key material with k={k}")
                    print(f"    r = {int_to_le_bytes(candidate, 16).hex()}")
                    print(f"    s = {int_to_le_bytes(s_candidate, 16).hex()}")
                    matching_impl = impl_name
                    recovered_r = candidate
                    recovered_s = s_candidate
                    found = True
                    break

        if not found:
            print(f"\n  {impl_name}: no valid clamped r found")

    if matching_impl is None:
        print("\nERROR: No implementation variant produced a valid key!")
        sys.exit(1)

    print(f"\n  -> Server uses implementation: {matching_impl}")

    # Validate recovered key against other traffic entries with same nonce
    print("\n  Validating against other traffic entries...")
    encoder = encoders[matching_impl]
    for entry in traffic:
        if entry["nonce_hex"] != reused_nonce:
            continue
        msg = bytes.fromhex(entry["message_hex"])
        expected_tag_int = le_bytes_to_int(bytes.fromhex(entry["authenticator_hex"]))
        acc = 0
        for i in range(0, len(msg), 16):
            chunk = msg[i:i+16]
            c = encoder(chunk)
            acc = ((acc + c) * recovered_r) % P
        computed_tag = (acc + recovered_s) % (1 << 128)
        valid = computed_tag == expected_tag_int
        print(f"    seq={entry['seq']}: {'VALID' if valid else 'INVALID'}")

    print("\n" + "=" * 60)
    print("STEP 4: Forge authenticator for target message")
    print("=" * 60)

    target_msg = bytes.fromhex(target["message_hex"])
    assert target["nonce_hex"] == reused_nonce, \
        "Target must use the reused nonce for forgery"
    assert len(target_msg) <= 16, "Target must be single-block"

    ct = encoder(target_msg)
    ht = (ct * recovered_r) % P
    forged_tag_int = (ht + recovered_s) % (1 << 128)
    forged_tag = int_to_le_bytes(forged_tag_int, 16)

    print(f"  Target message: {target_msg.decode(errors='replace')}")
    print(f"  Forged tag: {forged_tag.hex()}")

    # Verify with the compiled binary
    r_hex = int_to_le_bytes(recovered_r, 16).hex()
    s_hex = int_to_le_bytes(recovered_s, 16).hex()
    binary_tag = run_impl(matching_impl, r_hex, s_hex, target["message_hex"])
    print(f"  Binary verification ({matching_impl}): {binary_tag}")
    assert forged_tag.hex() == binary_tag, "Binary verification failed!"

    print("\n" + "=" * 60)
    print("STEP 5: Write output files")
    print("=" * 60)

    # Determine the deviation description
    if matching_impl == "beta":
        deviation = ("Message blocks are encoded as big-endian integers "
                     "instead of little-endian as specified by RFC 8439. "
                     "In the C code, mpz_import uses order=1 (big-endian) "
                     "rather than order=-1 (little-endian).")
    elif matching_impl == "gamma":
        deviation = ("Missing sentinel bit in message block encoding; "
                     "blocks are encoded without the high-bit padding "
                     "required by RFC 8439.")
    else:
        deviation = "Standard RFC 8439 behavior (no deviation)"

    vulnerability_assessment = (
        f"The deployed system has two critical security weaknesses. "
        f"First, the server's {matching_impl} implementation deviates from "
        f"RFC 8439 in its message block encoding, though this alone does not "
        f"enable attacks. Second, the captured traffic reveals nonce reuse: "
        f"nonce {reused_nonce} appears in sequences {affected_seqs}. "
        f"In Poly1305, the one-time key 's' is derived from the nonce, so "
        f"reusing a nonce means two messages share the same 's' value. "
        f"This allows an algebraic attack: the difference of two tags under "
        f"the same 's' eliminates 's' and exposes a linear equation in 'r' "
        f"over GF(2^130-5), from which 'r' can be recovered via modular "
        f"inversion. With 'r' and 's' both recovered, arbitrary messages "
        f"can be forged for that nonce."
    )

    audit_report = {
        "server_implementation": matching_impl,
        "implementation_deviation": deviation,
        "vulnerability_assessment": vulnerability_assessment
    }

    with open("/app/audit_report.json", "w") as f:
        json.dump(audit_report, f, indent=2)
    print(f"  Wrote /app/audit_report.json")

    with open("/app/forged_tag.hex", "w") as f:
        f.write(forged_tag.hex())
    print(f"  Wrote /app/forged_tag.hex: {forged_tag.hex()}")

    print("\n  DONE.")


if __name__ == "__main__":
    main()
