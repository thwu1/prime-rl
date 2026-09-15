#!/usr/bin/env python3
"""IEEE 802.11a/g OFDM PHY Layer Decoder — C/Python ctypes implementation.

Loads the Viterbi decoder from a compiled C shared library (viterbi.so)
via ctypes, and implements the remaining decode chain in Python:
deinterleaving, depuncturing, descrambling, byte extraction.
"""

import ctypes
import math
import os

# ── Load the C Viterbi shared library ────────────────────────────────

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
_viterbi_lib = ctypes.CDLL(os.path.join(_LIB_DIR, "viterbi.so"))

_viterbi_lib.viterbi_decode.argtypes = [
    ctypes.POINTER(ctypes.c_int),   # received
    ctypes.c_int,                    # n_data_bits
    ctypes.POINTER(ctypes.c_int),   # decoded (output)
]
_viterbi_lib.viterbi_decode.restype = ctypes.c_int


# ── MCS parameters ──────────────────────────────────────────────────

MCS_TABLE = [
    ("BPSK_1_2",    0b1011,  1,  48,   24),
    ("BPSK_3_4",    0b1111,  1,  48,   36),
    ("QPSK_1_2",    0b1010,  2,  96,   48),
    ("QPSK_3_4",    0b1110,  2,  96,   72),
    ("QAM16_1_2",   0b1001,  4,  192,  96),
    ("QAM16_3_4",   0b1101,  4,  192,  144),
    ("QAM64_2_3",   0b1000,  6,  288,  192),
    ("QAM64_3_4",   0b1100,  6,  288,  216),
]

RATE_TO_MCS = {entry[1]: idx for idx, entry in enumerate(MCS_TABLE)}


def _frame_params(mcs_index, psdu_length):
    _, rf, n_bpsc, n_cbps, n_dbps = MCS_TABLE[mcs_index]
    n_sym = math.ceil((16 + 8 * psdu_length + 6) / n_dbps)
    n_data = n_sym * n_dbps
    n_pad = n_data - (16 + 8 * psdu_length + 6)
    return dict(
        mcs=mcs_index, length=psdu_length,
        n_bpsc=n_bpsc, n_cbps=n_cbps, n_dbps=n_dbps,
        n_sym=n_sym, n_data=n_data, n_pad=n_pad,
    )


# ── Deinterleaver ───────────────────────────────────────────────────

def _deinterleave(bits, n_cbps, n_bpsc, n_sym):
    """Inverse of the IEEE 802.11a two-step block interleaver."""
    s = max(n_bpsc // 2, 1)
    first = [0] * n_cbps
    second = [0] * n_cbps
    for j in range(n_cbps):
        first[j] = s * (j // s) + ((j + (16 * j // n_cbps)) % s)
    for i in range(n_cbps):
        second[i] = 16 * i - (n_cbps - 1) * (16 * i // n_cbps)

    out = [0] * len(bits)
    for sym in range(n_sym):
        off = sym * n_cbps
        for k in range(n_cbps):
            out[off + second[first[k]]] = bits[off + k]
    return out


# ── Depuncturer ─────────────────────────────────────────────────────

def _depuncture(bits, mcs_index):
    """Re-insert erasures (value 2) where the puncturer removed bits."""
    if mcs_index in (0, 2, 4):
        return list(bits)

    pattern = [1, 1, 1, 0] if mcs_index == 6 else [1, 1, 1, 0, 0, 1]
    plen = len(pattern)

    out = []
    count = 0
    bit_idx = 0
    total = len(bits)

    while bit_idx < total:
        while pattern[count % plen] == 0:
            out.append(2)
            count += 1
        out.append(bits[bit_idx])
        count += 1
        bit_idx += 1
        while pattern[count % plen] == 0:
            out.append(2)
            count += 1

    return out


# ── Viterbi decode (C FFI) ──────────────────────────────────────────

def _viterbi_decode(received, n_data_bits):
    """Call the C Viterbi decoder via ctypes."""
    n_received = len(received)
    RecvArray = ctypes.c_int * n_received
    c_recv = RecvArray(*received)

    OutArray = ctypes.c_int * n_data_bits
    c_decoded = OutArray()

    ret = _viterbi_lib.viterbi_decode(c_recv, n_data_bits, c_decoded)
    if ret != 0:
        raise RuntimeError("C Viterbi decoder returned error")

    return list(c_decoded)


# ── Descrambler ─────────────────────────────────────────────────────

def _descramble(bits, n_data, seed):
    """Descramble using the x^7 + x^4 + 1 LFSR."""
    state = seed & 0x7F
    out = [0] * n_data
    for i in range(n_data):
        fb = ((state >> 6) & 1) ^ ((state >> 3) & 1)
        out[i] = fb ^ bits[i]
        state = ((state << 1) & 0x7E) | fb
    return out


# ── Byte extraction ────────────────────────────────────────────────

def _extract_bytes(bits, n_bytes):
    """Pack bits into bytes (LSB first), skipping 16-bit SERVICE field."""
    payload = bytearray(n_bytes)
    for i in range(n_bytes):
        byte_val = 0
        for b in range(8):
            byte_val |= bits[16 + i * 8 + b] << b
        payload[i] = byte_val
    return bytes(payload)


# ── SIGNAL field decoder ───────────────────────────────────────────

def _decode_signal_field(interleaved_48):
    """Decode the SIGNAL field from 48 interleaved BPSK rate-1/2 bits."""
    deint = _deinterleave(interleaved_48, 48, 1, 1)
    decoded = _viterbi_decode(deint, 24)

    rate_field = 0
    for i in range(4):
        rate_field |= decoded[i] << i

    length = 0
    for i in range(12):
        length |= decoded[5 + i] << i

    parity = 0
    for i in range(17):
        parity ^= decoded[i]
    if parity != decoded[17]:
        raise ValueError("SIGNAL field parity check failed")

    if rate_field not in RATE_TO_MCS:
        raise ValueError(f"Unknown RATE field value: {rate_field:#06b}")

    return {"mcs": RATE_TO_MCS[rate_field], "length": length}


# ── Public API ──────────────────────────────────────────────────────

def decode_frame(frame_bits, scrambler_seed):
    """Decode a complete IEEE 802.11a WLAN frame.

    Parameters
    ----------
    frame_bits : list[int]
        Interleaved coded bits (0 or 1).  First 48 are the SIGNAL field.
    scrambler_seed : int
        7-bit scrambler initialization value (1-127).

    Returns
    -------
    signal_info : dict
        ``{"mcs": int, "length": int}``
    payload : bytes
        Decoded PSDU (LENGTH bytes).
    """
    signal_info = _decode_signal_field(frame_bits[:48])
    fp = _frame_params(signal_info["mcs"], signal_info["length"])
    data_bits = frame_bits[48:]
    deint = _deinterleave(data_bits, fp["n_cbps"], fp["n_bpsc"], fp["n_sym"])
    depun = _depuncture(deint, fp["mcs"])
    decoded = _viterbi_decode(depun, fp["n_data"])
    descr = _descramble(decoded, fp["n_data"], scrambler_seed)
    payload = _extract_bytes(descr, fp["length"])
    return signal_info, payload
