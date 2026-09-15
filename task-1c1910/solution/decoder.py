#!/usr/bin/env python3
"""IEEE 802.11a protocol decoder: reads demodulated complex values and decodes payloads."""
import struct
import binascii
import os
import sys

G0 = 0x6d
G1 = 0x4f


def parity(x):
    x ^= x >> 16; x ^= x >> 8; x ^= x >> 4; x ^= x >> 2; x ^= x >> 1
    return x & 1


MCS_BY_RATE = {
    11: {'n_bpsc': 1, 'n_cbps': 48,  'n_dbps': 24,  'punct': [1, 1]},
    15: {'n_bpsc': 1, 'n_cbps': 48,  'n_dbps': 36,  'punct': [1, 1, 1, 0, 0, 1]},
    10: {'n_bpsc': 2, 'n_cbps': 96,  'n_dbps': 48,  'punct': [1, 1]},
    14: {'n_bpsc': 2, 'n_cbps': 96,  'n_dbps': 72,  'punct': [1, 1, 1, 0, 0, 1]},
     9: {'n_bpsc': 4, 'n_cbps': 192, 'n_dbps': 96,  'punct': [1, 1]},
    13: {'n_bpsc': 4, 'n_cbps': 192, 'n_dbps': 144, 'punct': [1, 1, 1, 0, 0, 1]},
     8: {'n_bpsc': 6, 'n_cbps': 288, 'n_dbps': 192, 'punct': [1, 1, 1, 0]},
    12: {'n_bpsc': 6, 'n_cbps': 288, 'n_dbps': 216, 'punct': [1, 1, 1, 0, 0, 1]},
}


def demap_bpsk(z):
    return int(z.real > 0)


def demap_qpsk(z):
    return 2 * int(z.imag > 0) + int(z.real > 0)


def demap_qam16(z):
    THRESH = 0.6324555320336759  # 2/sqrt(10)
    val = 0
    val |= int(z.real > 0)
    val |= 2 if abs(z.real) < THRESH else 0
    val |= 4 if z.imag > 0 else 0
    val |= 8 if abs(z.imag) < THRESH else 0
    return val


def demap_qam64(z):
    L = 0.1543033499620919  # 1/sqrt(42)
    re, im = z.real, z.imag
    val = 0
    val |= int(re > 0)
    val |= 2 if abs(re) < 4 * L else 0
    val |= 4 if (abs(re) < 6 * L and abs(re) > 2 * L) else 0
    val |= 8 if im > 0 else 0
    val |= 16 if abs(im) < 4 * L else 0
    val |= 32 if (abs(im) < 6 * L and abs(im) > 2 * L) else 0
    return val


DEMAPPERS = {1: demap_bpsk, 2: demap_qpsk, 4: demap_qam16, 6: demap_qam64}


def compute_perm(n_cbps, n_bpsc):
    s = max(n_bpsc // 2, 1)
    first = [0] * n_cbps
    second = [0] * n_cbps
    for j in range(n_cbps):
        first[j] = s * (j // s) + ((j + (16 * j // n_cbps)) % s)
    for i in range(n_cbps):
        second[i] = 16 * i - (n_cbps - 1) * (16 * i // n_cbps)
    return [second[first[k]] for k in range(n_cbps)]


def deinterleave(bits, n_cbps, n_bpsc):
    perm = compute_perm(n_cbps, n_bpsc)
    out = [0] * n_cbps
    for k in range(n_cbps):
        out[perm[k]] = bits[k]
    return out


def values_to_bits(values, n_bpsc):
    bits = []
    for val in values:
        for k in range(n_bpsc):
            bits.append((val >> k) & 1)
    return bits


def depuncture(bits, pattern):
    if pattern == [1, 1]:
        return list(bits)
    out = []
    for b in bits:
        while pattern[len(out) % len(pattern)] == 0:
            out.append(2)
        out.append(b)
    return out


def viterbi_decode(depunctured, n_data_bits):
    n_states = 64
    INF = float('inf')

    expected = {}
    for s in range(n_states):
        for b in range(2):
            reg = (s << 1) | b
            expected[(s, b)] = (parity(reg & G0), parity(reg & G1))

    pm = [INF] * n_states
    pm[0] = 0
    history = []
    n_pairs = len(depunctured) // 2

    for t in range(n_pairs):
        s0 = depunctured[2 * t]
        s1 = depunctured[2 * t + 1]
        new_pm = [INF] * n_states
        prev = [0] * n_states

        for s in range(n_states):
            if pm[s] >= INF:
                continue
            for b in range(2):
                ns = ((s << 1) | b) & 0x3F
                e0, e1 = expected[(s, b)]
                bm = 0
                if s0 != 2:
                    bm += int(s0 != e0)
                if s1 != 2:
                    bm += int(s1 != e1)
                total = pm[s] + bm
                if total < new_pm[ns]:
                    new_pm[ns] = total
                    prev[ns] = s

        pm = new_pm
        history.append(prev)

    best = min(range(n_states), key=lambda s: pm[s])
    decoded = []
    state = best
    for t in range(len(history) - 1, -1, -1):
        decoded.append(state & 1)
        state = history[t][state]
    decoded.reverse()
    return decoded[:n_data_bits]


def descramble(decoded_bits, psdu_size):
    state = 0
    for i in range(7):
        if decoded_bits[i]:
            state |= 1 << (6 - i)
    n_bytes = psdu_size + 2
    out = bytearray(n_bytes)
    out[0] = state
    for i in range(7, psdu_size * 8 + 16):
        feedback = ((state >> 6) & 1) ^ ((state >> 3) & 1)
        bit = feedback ^ (decoded_bits[i] & 1)
        out[i // 8] |= bit << (i % 8)
        state = ((state << 1) & 0x7E) | feedback
    return bytes(out)


def read_demod_file(path):
    """Read demodulated complex values from text file.
    Each line has 48 complex values as space-separated re im pairs."""
    symbols = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            complexes = []
            for i in range(0, len(parts), 2):
                z = complex(float(parts[i]), float(parts[i + 1]))
                complexes.append(z)
            symbols.append(complexes)
    return symbols


def decode_signal_field(signal_complex):
    signal_values = [demap_bpsk(z) for z in signal_complex]
    bits = deinterleave(signal_values, 48, 1)
    decoded = viterbi_decode(bits, 24)

    rate = 0
    psdu_size = 0
    p = False
    for i in range(17):
        p ^= decoded[i] > 0
        if i < 4 and decoded[i] > 0:
            rate |= 1 << i
        if i > 4 and i < 17 and decoded[i] > 0:
            psdu_size |= 1 << (i - 5)
    if p != (decoded[17] > 0):
        return None, None
    if rate not in MCS_BY_RATE:
        return None, None
    return rate, psdu_size


def decode_frame(demod_path):
    symbols = read_demod_file(demod_path)
    if not symbols:
        return None

    # First symbol is SIGNAL (always BPSK)
    signal_complex = symbols[0]
    rate, psdu_size = decode_signal_field(signal_complex)
    if rate is None:
        print(f"SIGNAL decode failed: {demod_path}", file=sys.stderr)
        return None

    mcs = MCS_BY_RATE[rate]
    n_dbps = mcs['n_dbps']
    n_cbps = mcs['n_cbps']
    n_bpsc = mcs['n_bpsc']
    punct = mcs['punct']

    total_bits = 16 + 8 * psdu_size + 6
    n_symbols = -(-total_bits // n_dbps)
    n_data_bits = n_symbols * n_dbps

    demap = DEMAPPERS[n_bpsc]

    all_deinterleaved = []
    for s in range(n_symbols):
        sym_complex = symbols[1 + s]
        values = [demap(z) for z in sym_complex]
        sym_bits = values_to_bits(values, n_bpsc)
        deinter = deinterleave(sym_bits, n_cbps, n_bpsc)
        all_deinterleaved.extend(deinter)

    depunctured = depuncture(all_deinterleaved, punct)
    decoded = viterbi_decode(depunctured, n_data_bits)
    out_bytes = descramble(decoded, psdu_size)

    psdu = out_bytes[2:psdu_size + 2]
    crc_check = binascii.crc32(psdu) & 0xFFFFFFFF
    if crc_check != 0x2144DF1C:
        print(f"CRC FAIL: {demod_path} (0x{crc_check:08X})", file=sys.stderr)
        return None

    return psdu[:-4]


def main():
    os.makedirs('/app/decoded', exist_ok=True)
    for idx in range(5):
        payload = decode_frame(f'/app/demod/frame_{idx}.txt')
        if payload is None:
            print(f"Frame {idx}: FAILED", file=sys.stderr)
            sys.exit(1)
        with open(f'/app/decoded/frame_{idx}.hex', 'w') as f:
            f.write(payload.hex())
        print(f"Frame {idx}: OK ({len(payload)} bytes)")


if __name__ == '__main__':
    main()
