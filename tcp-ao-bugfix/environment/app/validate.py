#!/usr/bin/env python3
"""
Validation script for TCP-AO implementation.
Tests KDF (traffic key derivation) and MAC computation against RFC 9235 test vectors.

Usage: python3 /app/validate.py
"""

import sys
sys.path.insert(0, '/app')

from tcp_ao import derive_traffic_key, compute_tcp_ao_mac

MASTER_KEY = b"testvector"

# ============================================================================
# KDF Test Vectors (RFC 9235 - all 24 unique traffic keys)
# ============================================================================
# Format: (label, kdf_alg, ip_version, src_addr, dst_addr,
#          src_port, dst_port, src_isn, dst_isn, expected_key_hex)

KDF_TESTS = [
    # Section 4.1 - IPv4 SHA-1 Covers Options
    ("4.1 send_syn", "HMAC-SHA1", 4,
     "10.11.12.13", "172.27.28.29", 59863, 179,
     0xfbfbab5a, 0,
     "6d63ef1b02fe1509d4b1402707fd7b0416abb74f"),
    ("4.1 recv_syn", "HMAC-SHA1", 4,
     "172.27.28.29", "10.11.12.13", 179, 59863,
     0x11c14261, 0xfbfbab5a,
     "d9e217e4834a80ca2f3fd8de2e41b8e6797fea96"),
    ("4.1 send_other", "HMAC-SHA1", 4,
     "10.11.12.13", "172.27.28.29", 59863, 179,
     0xfbfbab5a, 0x11c14261,
     "d2e59c65ffc7b1a39347656463b70edc24a13d71"),

    # Section 4.2 - IPv4 SHA-1 Omits Options
    ("4.2 send_syn", "HMAC-SHA1", 4,
     "10.11.12.13", "172.27.28.29", 65298, 179,
     0xcb0efbee, 0,
     "30eaa1560cf0be57dab5c045229fb10a423cd7ea"),
    ("4.2 recv_syn", "HMAC-SHA1", 4,
     "172.27.28.29", "10.11.12.13", 179, 65298,
     0xacd5b5e1, 0xcb0efbee,
     "b5b2896bb3664e8176b0edc6e799524101a8307f"),
    ("4.2 send_other", "HMAC-SHA1", 4,
     "10.11.12.13", "172.27.28.29", 65298, 179,
     0xcb0efbee, 0xacd5b5e1,
     "f3db1793d7910ecd806c34f155ea1f00345953e3"),

    # Section 5.1 - IPv4 AES-128 Covers Options
    ("5.1 send_syn", "AES-128-CMAC", 4,
     "10.11.12.13", "172.27.28.29", 50426, 179,
     0x787a1ddf, 0,
     "f5b8b3d5f34fdbb6eb8d4ab9660e60e3"),
    ("5.1 recv_syn", "AES-128-CMAC", 4,
     "172.27.28.29", "10.11.12.13", 179, 50426,
     0xfadd6de9, 0x787a1ddf,
     "4bc7571a486f3264bbd888474066b4b1"),
    ("5.1 send_other", "AES-128-CMAC", 4,
     "10.11.12.13", "172.27.28.29", 50426, 179,
     0x787a1ddf, 0xfadd6de9,
     "8c8ae0e8371ec5cbb97ea79d90418391"),

    # Section 5.2 - IPv4 AES-128 Omits Options
    ("5.2 send_syn", "AES-128-CMAC", 4,
     "10.11.12.13", "172.27.28.29", 55836, 179,
     0x389bed71, 0,
     "2cdbae1392c49449fa92c4509735d50e"),
    ("5.2 recv_syn", "AES-128-CMAC", 4,
     "172.27.28.29", "10.11.12.13", 179, 55836,
     0xd3844a6f, 0x389bed71,
     "3ce67a551869506b6347b633c50a624a"),
    ("5.2 send_other", "AES-128-CMAC", 4,
     "10.11.12.13", "172.27.28.29", 55836, 179,
     0x389bed71, 0xd3844a6f,
     "035bc400a341ffe595f59f58005006ca"),

    # Section 6.1 - IPv6 SHA-1 Covers Options
    ("6.1 send_syn", "HMAC-SHA1", 6,
     "fd00::1", "fd00::2", 63460, 179,
     0x176a833f, 0,
     "625ec09d575836edc9b6428418bbf06989a361bb"),
    ("6.1 recv_syn", "HMAC-SHA1", 6,
     "fd00::2", "fd00::1", 179, 63460,
     0x3f51994b, 0x176a833f,
     "e4a37ada2a0afca8711434913fe138c771ebcb4a"),
    ("6.1 send_other", "HMAC-SHA1", 6,
     "fd00::1", "fd00::2", 63460, 179,
     0x176a833f, 0x3f51994b,
     "1ed82975f4ea444c61580c5bd90dbd61bbc91b7e"),

    # Section 6.2 - IPv6 SHA-1 Omits Options
    ("6.2 send_syn", "HMAC-SHA1", 6,
     "fd00::1", "fd00::2", 50893, 179,
     0x020c1e69, 0,
     "31a3faf69effae52931b7f845467315c270a4edc"),
    ("6.2 recv_syn", "HMAC-SHA1", 6,
     "fd00::2", "fd00::1", 179, 50893,
     0xeba3734d, 0x020c1e69,
     "405108947f996575e7bdbc26d40216a2c7fa91bd"),
    ("6.2 send_other", "HMAC-SHA1", 6,
     "fd00::1", "fd00::2", 50893, 179,
     0x020c1e69, 0xeba3734d,
     "b34eed6a9396a669f1c4f4f57618f3656f52c7ab"),

    # Section 7.1 - IPv6 AES-128 Covers Options
    ("7.1 send_syn", "AES-128-CMAC", 6,
     "fd00::1", "fd00::2", 63578, 179,
     0x193cccec, 0,
     "fa5a2108882d39d0c71929175ab1b7b8"),
    ("7.1 recv_syn", "AES-128-CMAC", 6,
     "fd00::2", "fd00::1", 179, 63578,
     0xa6744ecb, 0x193cccec,
     "cf1b1e225e06a63616764a067b46f4b1"),
    ("7.1 send_other", "AES-128-CMAC", 6,
     "fd00::1", "fd00::2", 63578, 179,
     0x193cccec, 0xa6744ecb,
     "6174c3557abed27574dba37185f00300"),

    # Section 7.2 - IPv6 AES-128 Omits Options
    ("7.2 send_syn", "AES-128-CMAC", 6,
     "fd00::1", "fd00::2", 62088, 179,
     0xb01da74a, 0,
     "a94f511263e4093d35dd818c13bbbf53"),
    ("7.2 recv_syn", "AES-128-CMAC", 6,
     "fd00::2", "fd00::1", 179, 62088,
     0xa6246145, 0xb01da74a,
     "92dea5bbc78b1d9f5b2952e9cd30642a"),
    ("7.2 send_other", "AES-128-CMAC", 6,
     "fd00::1", "fd00::2", 62088, 179,
     0xb01da74a, 0xa6246145,
     "4fb2086e402c679079ed65d4bf97693d"),
]

# ============================================================================
# MAC Test Vectors (RFC 9235 - representative SYN packets)
# ============================================================================
# Format: (label, mac_alg, covers_options, traffic_key_hex, packet_hex, expected_mac_hex)

MAC_TESTS = [
    # 4.1.1 - IPv4 SHA-1 Covers, Client SYN
    ("4.1.1 SYN",
     "HMAC-SHA-1-96", True,
     "6d63ef1b02fe1509d4b1402707fd7b0416abb74f",
     "45e0004cdd0f4000ff06bf6b0a0b0c0dac1b1c1d"
     "e9d700b3fbfbab5a00000000e002ffffcac40000"
     "020405b4010303080402080a00155ab700000000"
     "1d103d542ee437c6f8ede6d7c4d602e7",
     "2ee437c6f8ede6d7c4d602e7"),

    # 4.2.1 - IPv4 SHA-1 Omits, Client SYN
    ("4.2.1 SYN",
     "HMAC-SHA-1-96", False,
     "30eaa1560cf0be57dab5c045229fb10a423cd7ea",
     "45e0004c53994000ff0648e20a0b0c0dac1b1c1d"
     "ff1200b3cb0efbee00000000e002ffff541f0000"
     "020405b4010303080402080a00024cce00000000"
     "1d103d5480af3cfeb85368937b8f9ec2",
     "80af3cfeb85368937b8f9ec2"),

    # 5.1.1 - IPv4 AES-128 Covers, Client SYN
    ("5.1.1 SYN",
     "AES-128-CMAC-96", True,
     "f5b8b3d5f34fdbb6eb8d4ab9660e60e3",
     "45e0004c7b9f4000ff0620dc0a0b0c0dac1b1c1d"
     "c4fa00b3787a1ddf00000000e002ffff5a0f0000"
     "020405b4010303080402080a00017ed000000000"
     "1d103d54e477e99c8040765498e55091",
     "e477e99c8040765498e55091"),

    # 6.1.1 - IPv6 SHA-1 Covers, Client SYN
    ("6.1.1 SYN",
     "HMAC-SHA-1-96", True,
     "625ec09d575836edc9b6428418bbf06989a361bb",
     "6e0891dc00380640"
     "fd000000000000000000000000000001"
     "fd000000000000000000000000000002"
     "f7e400b3176a833f00000000"
     "e002ffff47210000020405a0"
     "010303080402080a0041d08700000000"
     "1d103d549033ec3d7334b64c5edd039f",
     "9033ec3d7334b64c5edd039f"),

    # 7.1.1 - IPv6 AES-128 Covers, Client SYN
    ("7.1.1 SYN",
     "AES-128-CMAC-96", True,
     "fa5a2108882d39d0c71929175ab1b7b8",
     "6e04a70600380640"
     "fd000000000000000000000000000001"
     "fd000000000000000000000000000002"
     "f85a00b3193cccec00000000"
     "e002ffffde5d0000020405a0"
     "010303080402080a13e4ab9900000000"
     "1d103d5459b588107481ac6dc3927040",
     "59b588107481ac6dc3927040"),
]


def run_kdf_tests():
    """Run all KDF tests and report results."""
    print("=" * 70)
    print("KDF (Traffic Key Derivation) Tests")
    print("=" * 70)
    passed = 0
    failed = 0
    for entry in KDF_TESTS:
        label, kdf_alg, ip_ver, src, dst, sp, dp, si, di, expected = entry
        try:
            key = derive_traffic_key(MASTER_KEY, kdf_alg, src, dst,
                                     sp, dp, si, di, ip_ver)
            actual = key.hex()
            if actual == expected:
                print(f"  PASS  {label}")
                passed += 1
            else:
                print(f"  FAIL  {label}")
                print(f"        expected: {expected}")
                print(f"        actual:   {actual}")
                failed += 1
        except Exception as e:
            print(f"  ERROR {label}: {e}")
            failed += 1
    return passed, failed


def run_mac_tests():
    """Run all MAC tests and report results."""
    print("\n" + "=" * 70)
    print("MAC Computation Tests")
    print("=" * 70)
    passed = 0
    failed = 0
    for entry in MAC_TESTS:
        label, mac_alg, covers, tk_hex, pkt_hex, expected = entry
        try:
            tk = bytes.fromhex(tk_hex)
            pkt = bytes.fromhex(pkt_hex)
            mac = compute_tcp_ao_mac(tk, pkt, 0, covers, mac_alg)
            actual = mac.hex()
            if actual == expected:
                print(f"  PASS  {label}")
                passed += 1
            else:
                print(f"  FAIL  {label}")
                print(f"        expected: {expected}")
                print(f"        actual:   {actual}")
                failed += 1
        except Exception as e:
            print(f"  ERROR {label}: {e}")
            failed += 1
    return passed, failed


def main():
    print("TCP-AO Implementation Validator (RFC 9235 Test Vectors)")
    print()

    kdf_pass, kdf_fail = run_kdf_tests()
    mac_pass, mac_fail = run_mac_tests()

    total_pass = kdf_pass + mac_pass
    total_fail = kdf_fail + mac_fail
    total = total_pass + total_fail

    print("\n" + "=" * 70)
    print(f"Results: {total_pass}/{total} passed, {total_fail}/{total} failed")
    if total_fail == 0:
        print("All tests passed!")
    else:
        print(f"\n{total_fail} test(s) need fixing.")
    print("=" * 70)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
