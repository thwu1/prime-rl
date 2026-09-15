#!/usr/bin/env python3
"""
SIGMA-7 Fixed-Code Receiver Facility Simulator

Simulates shift-register based fixed-code receivers for a multi-zone
secure facility. Each zone uses a different configuration of alphabet
size, code length, and optional physical encoding.

Usage:
  python3 /app/simulator.py info
  python3 /app/simulator.py crack <zone_id> <sequence_file>

Arguments:
  zone_id        : Zone identifier (A, B, C, D, or E)
  sequence_file  : Path to file containing space-separated integers.
                   For encoded zones, provide physical bits.
                   For unencoded zones, provide logical symbols.

Exit codes:
  0 = all target receivers cracked
  1 = not cracked
  2 = input error
"""

import sys
import json
import hashlib
import os


def _facility_key(zone_label, alphabet_size, code_length):
    """Derive the fixed access code for a given zone configuration."""
    material = "b7e9a12f4d5c8031:{zl}:{asz}:{cl}".format(
        zl=zone_label, asz=alphabet_size, cl=code_length
    )
    digest = hashlib.sha256(material.encode()).digest()
    return [digest[i % len(digest)] % alphabet_size for i in range(code_length)]


class ShiftRegisterReceiver:
    """Models a fixed-code receiver using a shift register.

    Incoming symbols are pushed one at a time into a FIFO register
    of length n (the code length). After each push, the register
    contents are compared against the secret code. On the first
    match the receiver signals 'access granted'.
    """

    def __init__(self, secret_code, alphabet_size):
        self._secret = list(secret_code)
        self._length = len(secret_code)
        self._k = alphabet_size
        self._register = [0] * self._length
        self._count = 0
        self._match_pos = -1

    def process_symbol(self, symbol):
        """Push one symbol into the shift register. Returns True on first match."""
        if symbol < 0 or symbol >= self._k:
            raise ValueError(
                "Symbol {} not in alphabet [0, {})".format(symbol, self._k)
            )
        self._register.pop(0)
        self._register.append(symbol)
        self._count += 1
        if (self._count >= self._length
                and self._register == self._secret
                and self._match_pos < 0):
            self._match_pos = self._count
            return True
        return False

    @property
    def matched(self):
        return self._match_pos > 0

    @property
    def match_position(self):
        return self._match_pos

    @property
    def secret(self):
        return list(self._secret)


def _load_config():
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.json"
    )
    with open(config_path) as f:
        return json.load(f)


def _decode_encoded_stream(raw_bits, encoding_map):
    """Decode physical bits to logical symbols using encoding map."""
    symbol_bit_length = len(next(iter(encoding_map.values())))
    reverse_map = {}
    for sym_str, pattern in encoding_map.items():
        reverse_map[pattern] = int(sym_str)

    decoded = []
    for i in range(0, len(raw_bits), symbol_bit_length):
        chunk = "".join(str(b) for b in raw_bits[i:i + symbol_bit_length])
        if len(chunk) < symbol_bit_length:
            print(
                "Warning: trailing {} bits ignored".format(len(chunk)),
                file=sys.stderr,
            )
            break
        if chunk not in reverse_map:
            print(
                "Decode error at bit {}: unknown pattern '{}'".format(i, chunk),
                file=sys.stderr,
            )
            sys.exit(2)
        decoded.append(reverse_map[chunk])
    return decoded


def cmd_info(config):
    """Display facility zone information."""
    print("=" * 50)
    print("SIGMA-7 Fixed-Code Access Control Facility")
    print("=" * 50)
    for zone_id in sorted(config["zones"]):
        zone = config["zones"][zone_id]
        print("\n[Zone {}] {}".format(zone_id, zone["name"]))
        print("  {}".format(zone.get("description", "")))
        if "n_min" in zone:
            print("  Alphabet size (k): {}".format(zone["k"]))
            print("  Code lengths: {} through {}".format(
                zone["n_min"], zone["n_max"]
            ))
        else:
            print("  Alphabet size (k): {}".format(zone["k"]))
            print("  Code length (n): {}".format(zone["n"]))
        if zone.get("encoding"):
            print("  Physical encoding:")
            for sym, pattern in zone["encoding"].items():
                print("    Symbol {} -> {}".format(sym, pattern))
            print("  (Sequence file must contain encoded physical bits)")


def cmd_crack(config, zone_id, sequence_file):
    """Attempt to crack a zone using a symbol/bit sequence."""
    if zone_id not in config["zones"]:
        print("Error: unknown zone '{}'".format(zone_id), file=sys.stderr)
        sys.exit(2)

    zone = config["zones"][zone_id]
    k = zone["k"]

    with open(sequence_file) as f:
        raw = list(map(int, f.read().split()))

    if zone.get("encoding"):
        symbols = _decode_encoded_stream(raw, zone["encoding"])
    else:
        symbols = raw

    if zone_id == "E":
        n_min, n_max = zone["n_min"], zone["n_max"]
        receivers = {}
        for n in range(n_min, n_max + 1):
            code = _facility_key("E_{}".format(n), k, n)
            receivers[n] = ShiftRegisterReceiver(code, k)

        for s in symbols:
            for rcv in receivers.values():
                rcv.process_symbol(s)

        all_cracked = True
        print("Zone E Multi-Length Results:")
        for n in sorted(receivers):
            rcv = receivers[n]
            if rcv.matched:
                code_str = "".join(map(str, rcv.secret))
                print("  n={}: CRACKED at position {}, code={}".format(
                    n, rcv.match_position, code_str
                ))
            else:
                print("  n={}: FAILED".format(n))
                all_cracked = False

        sys.exit(0 if all_cracked else 1)
    else:
        n = zone["n"]
        code = _facility_key(zone_id, k, n)
        rcv = ShiftRegisterReceiver(code, k)

        for s in symbols:
            rcv.process_symbol(s)

        if rcv.matched:
            code_str = "".join(map(str, rcv.secret))
            print("CRACKED at position {}, code={}".format(
                rcv.match_position, code_str
            ))
            sys.exit(0)
        else:
            print("ACCESS DENIED - code not found in sequence")
            sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    config = _load_config()
    command = sys.argv[1]

    if command == "info":
        cmd_info(config)
    elif command == "crack":
        if len(sys.argv) != 4:
            print(
                "Usage: python3 /app/simulator.py crack <zone_id> <sequence_file>",
                file=sys.stderr,
            )
            sys.exit(2)
        cmd_crack(config, sys.argv[2], sys.argv[3])
    else:
        print("Unknown command: {}".format(command), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
