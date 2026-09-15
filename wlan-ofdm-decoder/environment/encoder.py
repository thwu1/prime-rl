#!/usr/bin/env python3
"""IEEE 802.11a/g OFDM PHY Layer Encoder.

Implements the complete transmit encoding chain as defined in IEEE Std
802.11-2020, Section 17 (OFDM PHY):

    payload bytes
      -> bit unpacking (LSB-first per byte)
      -> PLCP SERVICE field prepend (16 zero bits)
      -> scrambling (x^7 + x^4 + 1 LFSR)
      -> tail-bit reset (6 zeros to flush encoder)
      -> rate-1/2 convolutional coding (K=7, g0=0o155 g1=0o117)
      -> puncturing (rate 2/3 or 3/4 patterns)
      -> block interleaving (two-step permutation per OFDM symbol)

A separate SIGNAL field (24 bits, always BPSK rate 1/2) is prepended to
the interleaved data stream.

All bit arrays use one Python int (0 or 1) per bit.
"""

import math

# ── MCS table (IEEE 802.11a Table 17-3) ──────────────────────────────
#   (name, RATE field value, n_bpsc, n_cbps, n_dbps)
MCS_TABLE = [
    ("BPSK_1_2",  0b1011, 1,  48,  24),   # MCS 0
    ("BPSK_3_4",  0b1111, 1,  48,  36),   # MCS 1
    ("QPSK_1_2",  0b1010, 2,  96,  48),   # MCS 2
    ("QPSK_3_4",  0b1110, 2,  96,  72),   # MCS 3
    ("QAM16_1_2", 0b1001, 4, 192,  96),   # MCS 4
    ("QAM16_3_4", 0b1101, 4, 192, 144),   # MCS 5
    ("QAM64_2_3", 0b1000, 6, 288, 192),   # MCS 6
    ("QAM64_3_4", 0b1100, 6, 288, 216),   # MCS 7
]


def frame_params(mcs_index, psdu_length):
    """Compute OFDM frame parameters for a given MCS and PSDU length.

    Returns a dict with keys: mcs, length, rate_field, n_bpsc, n_cbps,
    n_dbps, n_sym, n_data, n_pad.
    """
    _, rate_field, n_bpsc, n_cbps, n_dbps = MCS_TABLE[mcs_index]
    # Number of OFDM symbols needed to carry SERVICE + PSDU + TAIL
    n_sym = math.ceil((16 + 8 * psdu_length + 6) / n_dbps)
    n_data = n_sym * n_dbps          # total coded data bits
    n_pad = n_data - (16 + 8 * psdu_length + 6)
    return dict(
        mcs=mcs_index, length=psdu_length,
        rate_field=rate_field, n_bpsc=n_bpsc,
        n_cbps=n_cbps, n_dbps=n_dbps,
        n_sym=n_sym, n_data=n_data, n_pad=n_pad,
    )


# ── Internal encoding stages ─────────────────────────────────────────

def _generate_bits(data, n_data):
    """Unpack *data* bytes into a bit vector of length *n_data*.

    The first 16 positions are the SERVICE field (all zeros).
    Data bytes follow in LSB-first order.  Remaining positions (tail +
    pad) are zero-filled.
    """
    bits = [0] * n_data
    for i, byte in enumerate(data):
        for b in range(8):
            bits[16 + i * 8 + b] = (byte >> b) & 1
    return bits


def _scramble(bits, n_data, n_pad, seed):
    """Scramble using the 802.11 LFSR (polynomial x^7 + x^4 + 1).

    *seed* is a 7-bit non-zero initialization value (1-127).
    After scrambling the tail bits (last 6 before padding) are reset to
    zero so the convolutional encoder is flushed to the all-zero state.
    """
    state = seed & 0x7F
    out = [0] * n_data
    for i in range(n_data):
        fb = ((state >> 6) & 1) ^ ((state >> 3) & 1)
        out[i] = fb ^ bits[i]
        state = ((state << 1) & 0x7E) | fb
    # Reset tail bits to zero (flush convolutional encoder)
    tail_start = n_data - n_pad - 6
    for j in range(6):
        out[tail_start + j] = 0
    return out


def _conv_encode(scrambled, n_data):
    """Rate-1/2 convolutional encoder.

    Constraint length K = 7 (64-state trellis).
    Generator polynomials (octal): g0 = 0155, g1 = 0117.
    The 7-bit shift-register state includes the current input bit at
    position 0.
    """
    state = 0
    enc = [0] * (2 * n_data)
    for i in range(n_data):
        state = ((state << 1) & 0x7E) | scrambled[i]
        enc[2 * i]     = bin(state & 0o155).count('1') % 2
        enc[2 * i + 1] = bin(state & 0o117).count('1') % 2
    return enc


def _puncture(encoded, mcs_index):
    """Puncture encoded bits to achieve the target code rate.

    Rate 1/2 (MCS 0, 2, 4): no bits removed.
    Rate 2/3 (MCS 6):        remove every bit where i mod 4 == 3.
    Rate 3/4 (MCS 1,3,5,7):  remove bits where i mod 6 in {3, 4}.
    """
    if mcs_index in (0, 2, 4):
        return list(encoded)
    out = []
    for i, b in enumerate(encoded):
        if mcs_index == 6:                    # rate 2/3
            if i % 4 != 3:
                out.append(b)
        else:                                 # rate 3/4
            if i % 6 not in (3, 4):
                out.append(b)
    return out


def _interleave(bits, n_cbps, n_bpsc, n_sym):
    """Two-step block interleaver (IEEE 802.11a Section 17.3.5.6).

    Permutation applied independently to each OFDM symbol of *n_cbps*
    coded bits.

    First permutation:
        f(j) = s * floor(j/s) + (j + floor(16*j/n_cbps)) mod s
    Second permutation:
        g(i) = 16*i - (n_cbps - 1) * floor(16*i / n_cbps)

    Encoding direction: interleaved[k] = coded[ g(f(k)) ]

    *s* = max(n_bpsc / 2, 1).
    """
    s = max(n_bpsc // 2, 1)
    first  = [0] * n_cbps
    second = [0] * n_cbps
    for j in range(n_cbps):
        first[j] = s * (j // s) + ((j + (16 * j // n_cbps)) % s)
    for i in range(n_cbps):
        second[i] = 16 * i - (n_cbps - 1) * (16 * i // n_cbps)
    out = [0] * (n_sym * n_cbps)
    for sym in range(n_sym):
        off = sym * n_cbps
        for k in range(n_cbps):
            out[off + k] = bits[off + second[first[k]]]
    return out


# ── SIGNAL field ──────────────────────────────────────────────────────

def encode_signal(mcs_index, psdu_length):
    """Encode the 24-bit SIGNAL field into 48 interleaved BPSK bits.

    The SIGNAL field is always transmitted at BPSK rate 1/2 (no
    scrambling, no puncturing).

    Layout (24 bits before coding):
        bits 0-3   : RATE (4-bit MCS indicator, LSB first)
        bit  4     : Reserved (0)
        bits 5-16  : LENGTH (PSDU byte count, 12 bits LSB first)
        bit  17    : even parity over bits 0-16
        bits 18-23 : tail (all zeros)
    """
    rate_field = MCS_TABLE[mcs_index][1]
    sig = [0] * 24
    for i in range(4):
        sig[i] = (rate_field >> i) & 1
    for i in range(12):
        sig[5 + i] = (psdu_length >> i) & 1
    parity = 0
    for i in range(17):
        parity ^= sig[i]
    sig[17] = parity
    # Convolutional encode at rate 1/2 (no scrambling)
    state = 0
    enc = [0] * 48
    for i in range(24):
        state = ((state << 1) & 0x7E) | sig[i]
        enc[2 * i]     = bin(state & 0o155).count('1') % 2
        enc[2 * i + 1] = bin(state & 0o117).count('1') % 2
    return _interleave(enc, 48, 1, 1)


# ── Public API ────────────────────────────────────────────────────────

def encode_frame(data, mcs_index, scrambler_seed=1):
    """Encode a complete WLAN frame (SIGNAL + DATA).

    Parameters
    ----------
    data : bytes
        PSDU payload (1-4095 bytes).
    mcs_index : int
        Modulation and coding scheme (0-7).
    scrambler_seed : int
        7-bit scrambler initialization (1-127).

    Returns
    -------
    frame_bits : list[int]
        Interleaved bit sequence (one int per bit, values 0 or 1).
        First 48 elements are the SIGNAL field; the rest are DATA.
    params : dict
        Frame parameters (see :func:`frame_params`).
    """
    fp = frame_params(mcs_index, len(data))

    sig = encode_signal(mcs_index, len(data))

    bits = _generate_bits(data, fp["n_data"])
    scr  = _scramble(bits, fp["n_data"], fp["n_pad"], scrambler_seed)
    enc  = _conv_encode(scr, fp["n_data"])
    pun  = _puncture(enc, mcs_index)
    itl  = _interleave(pun, fp["n_cbps"], fp["n_bpsc"], fp["n_sym"])

    return sig + itl, fp
