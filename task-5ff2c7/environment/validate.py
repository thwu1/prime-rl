#!/usr/bin/env python3
"""Validate SP 800-185 implementation against NIST test vectors.

Requires libkeccak.so to be built first (run 'make' in /app/).
Tests the Keccak-f[1600] permutation, cSHAKE, KMAC, and TupleHash
against official NIST-published example values.
"""

import json
import sys
import os

sys.path.insert(0, '/app')


def load_vectors():
    with open('/app/test_vectors.json') as f:
        return json.load(f)


def run_cshake_tests(vectors):
    from sp800_185 import cshake
    passed, failed = 0, 0
    for tv in vectors:
        data = bytes.fromhex(tv['data'])
        N = tv['N'].encode()
        S = tv['S'].encode()
        try:
            result = cshake(tv['security'], data, tv['output_bits'], N, S)
            result_hex = result.hex()
            if result_hex == tv['expected']:
                print(f"  PASS: {tv['name']}")
                passed += 1
            else:
                print(f"  FAIL: {tv['name']}")
                print(f"    expected: {tv['expected']}")
                print(f"    got:      {result_hex}")
                failed += 1
        except Exception as e:
            print(f"  ERROR: {tv['name']}: {e}")
            failed += 1
    return passed, failed


def run_kmac_tests(vectors):
    from sp800_185 import kmac
    passed, failed = 0, 0
    for tv in vectors:
        key = bytes.fromhex(tv['key'])
        data = bytes.fromhex(tv['data'])
        S = tv['S'].encode()
        try:
            result = kmac(tv['security'], key, data, tv['output_bits'], S)
            result_hex = result.hex()
            if result_hex == tv['expected']:
                print(f"  PASS: {tv['name']}")
                passed += 1
            else:
                print(f"  FAIL: {tv['name']}")
                print(f"    expected: {tv['expected']}")
                print(f"    got:      {result_hex}")
                failed += 1
        except Exception as e:
            print(f"  ERROR: {tv['name']}: {e}")
            failed += 1
    return passed, failed


def run_tuplehash_tests(vectors):
    from sp800_185 import tuplehash
    passed, failed = 0, 0
    for tv in vectors:
        tuples = [bytes.fromhex(t) for t in tv['tuples']]
        S = tv['S'].encode()
        try:
            result = tuplehash(tv['security'], tuples, tv['output_bits'], S)
            result_hex = result.hex()
            if result_hex == tv['expected']:
                print(f"  PASS: {tv['name']}")
                passed += 1
            else:
                print(f"  FAIL: {tv['name']}")
                print(f"    expected: {tv['expected']}")
                print(f"    got:      {result_hex}")
                failed += 1
        except Exception as e:
            print(f"  ERROR: {tv['name']}: {e}")
            failed += 1
    return passed, failed


def run_permutation_test(ref):
    from sp800_185 import keccak_f1600
    input_block = bytes.fromhex(ref['input_block_hex'])
    expected = ref['expected_state_after_permutation_hex']
    state = bytearray(200)
    for i in range(len(input_block)):
        state[i] ^= input_block[i]
    result = keccak_f1600(bytes(state))
    result_hex = result.hex()
    if result_hex == expected:
        print("  PASS: Keccak-f[1600] permutation reference")
        return 1, 0
    else:
        print("  FAIL: Keccak-f[1600] permutation reference")
        print(f"    expected: {expected[:64]}...")
        print(f"    got:      {result_hex[:64]}...")
        return 0, 1


def main():
    vectors = load_vectors()
    total_pass, total_fail = 0, 0

    print("=== Keccak-f[1600] Permutation ===")
    p, f = run_permutation_test(vectors['debug_reference'])
    total_pass += p
    total_fail += f

    print("\n=== cSHAKE Tests ===")
    p, f = run_cshake_tests(vectors['cshake'])
    total_pass += p
    total_fail += f

    print("\n=== KMAC Tests ===")
    p, f = run_kmac_tests(vectors['kmac'])
    total_pass += p
    total_fail += f

    print("\n=== TupleHash Tests ===")
    p, f = run_tuplehash_tests(vectors['tuplehash'])
    total_pass += p
    total_fail += f

    print(f"\n{'='*40}")
    print(f"Total: {total_pass} passed, {total_fail} failed out of {total_pass + total_fail}")
    return 0 if total_fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
