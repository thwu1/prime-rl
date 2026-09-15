#!/usr/bin/env python3
"""Generate IEEE 802.11a WiFi frame captures as binary IQ samples with channel effects."""
import numpy as np
import json
import hashlib
import struct
import binascii
import os

G0 = 0x6d
G1 = 0x4f

def parity(x):
    x ^= x >> 16; x ^= x >> 8; x ^= x >> 4; x ^= x >> 2; x ^= x >> 1
    return x & 1

def make_payload(frame_idx, size):
    data = bytearray()
    chunk = 0
    while len(data) < size:
        h = hashlib.sha256(f"wifi_frame_{frame_idx}_chunk_{chunk}".encode()).digest()
        data.extend(h)
        chunk += 1
    return bytes(data[:size])

def bytes_to_bits(data):
    bits = []
    for byte in data:
        for i in range(8):
            bits.append((byte >> i) & 1)
    return bits

def scramble(bits, seed):
    state = seed & 0x7F
    out = []
    for bit in bits:
        feedback = ((state >> 6) & 1) ^ ((state >> 3) & 1)
        out.append(bit ^ feedback)
        state = ((state << 1) & 0x7E) | feedback
    return out

def conv_encode(bits):
    state = 0
    output = []
    for b in bits:
        reg = (state << 1) | b
        output.append(parity(reg & G0))
        output.append(parity(reg & G1))
        state = reg & 0x3F
    return output

def puncture(bits, pattern):
    return [bit for i, bit in enumerate(bits) if pattern[i % len(pattern)] == 1]

def compute_perm(n_cbps, n_bpsc):
    s = max(n_bpsc // 2, 1)
    first = [0] * n_cbps
    second = [0] * n_cbps
    for j in range(n_cbps):
        first[j] = s * (j // s) + ((j + (16 * j // n_cbps)) % s)
    for i in range(n_cbps):
        second[i] = 16 * i - (n_cbps - 1) * (16 * i // n_cbps)
    return [second[first[k]] for k in range(n_cbps)]

def interleave(bits, n_cbps, n_bpsc):
    perm = compute_perm(n_cbps, n_bpsc)
    return [bits[perm[k]] for k in range(n_cbps)]

def bits_to_values(bits, n_bpsc):
    values = []
    for i in range(0, len(bits), n_bpsc):
        val = 0
        for k in range(n_bpsc):
            val |= bits[i + k] << k
        values.append(val)
    return values

def encode_signal_field(rate_val, psdu_size):
    signal = [0] * 24
    for i in range(4):
        signal[i] = (rate_val >> i) & 1
    for i in range(12):
        signal[5 + i] = (psdu_size >> i) & 1
    p = 0
    for i in range(17):
        p ^= signal[i]
    signal[17] = p
    coded = conv_encode(signal)
    return interleave(coded, 48, 1)

MCS = {
    'BPSK_1_2':  {'rate_val': 11, 'n_bpsc': 1, 'n_cbps': 48,  'n_dbps': 24,  'punct': [1, 1]},
    'BPSK_3_4':  {'rate_val': 15, 'n_bpsc': 1, 'n_cbps': 48,  'n_dbps': 36,  'punct': [1, 1, 1, 0, 0, 1]},
    'QPSK_1_2':  {'rate_val': 10, 'n_bpsc': 2, 'n_cbps': 96,  'n_dbps': 48,  'punct': [1, 1]},
    'QPSK_3_4':  {'rate_val': 14, 'n_bpsc': 2, 'n_cbps': 96,  'n_dbps': 72,  'punct': [1, 1, 1, 0, 0, 1]},
    'QAM16_1_2': {'rate_val':  9, 'n_bpsc': 4, 'n_cbps': 192, 'n_dbps': 96,  'punct': [1, 1]},
    'QAM16_3_4': {'rate_val': 13, 'n_bpsc': 4, 'n_cbps': 192, 'n_dbps': 144, 'punct': [1, 1, 1, 0, 0, 1]},
    'QAM64_2_3': {'rate_val':  8, 'n_bpsc': 6, 'n_cbps': 288, 'n_dbps': 192, 'punct': [1, 1, 1, 0]},
    'QAM64_3_4': {'rate_val': 12, 'n_bpsc': 6, 'n_cbps': 288, 'n_dbps': 216, 'punct': [1, 1, 1, 0, 0, 1]},
}

# LTS in fftshift order (index 0 = subcarrier -32, index 32 = DC, index 63 = subcarrier +31)
LTS_FFTSHIFT = np.array([
    0, 0, 0, 0, 0, 0,
    1, 1, -1, -1, 1, 1, -1, 1, -1, 1,
    1, 1, 1, 1, 1, -1, -1, 1, 1, -1, 1, -1, 1, 1, 1, 1,
    0,
    1, -1, -1, 1, 1, -1, 1, -1, 1, -1, -1, -1, -1, -1, 1, 1,
    -1, -1, 1, -1, 1, -1, 1, 1, 1, 1,
    0, 0, 0, 0, 0
], dtype=np.complex128)

NULL_INDICES = [0, 1, 2, 3, 4, 5, 32, 59, 60, 61, 62, 63]
PILOT_INDICES = [11, 25, 39, 53]
DATA_INDICES = sorted([i for i in range(64) if i not in NULL_INDICES and i not in PILOT_INDICES])

POLARITY = [
    1, 1, 1, 1, -1, -1, -1, 1, -1, -1, -1, -1, 1, 1, -1, 1,
    -1, -1, 1, 1, -1, 1, 1, -1, 1, 1, 1, 1, 1, 1, -1, 1,
    1, 1, -1, 1, 1, -1, -1, 1, 1, 1, -1, 1, -1, -1, -1, 1,
    -1, 1, -1, -1, 1, -1, -1, 1, 1, 1, 1, 1, -1, -1, 1, 1,
    -1, -1, 1, -1, 1, -1, 1, 1, -1, -1, -1, 1, 1, -1, -1, -1,
    -1, 1, -1, -1, 1, -1, 1, 1, 1, 1, -1, 1, -1, 1, -1, 1,
    -1, -1, -1, -1, -1, 1, -1, 1, 1, -1, 1, -1, 1, 1, 1, -1,
    -1, 1, -1, -1, -1, 1, 1, 1, -1, -1, -1, -1, -1, -1, -1
]

BPSK_TABLE = np.array([-1.0+0j, 1.0+0j])

_QL = 1.0 / np.sqrt(2)
QPSK_TABLE = np.array([
    complex(-_QL, -_QL), complex(_QL, -_QL),
    complex(-_QL, _QL), complex(_QL, _QL),
])

_Q16L = 1.0 / np.sqrt(10)
QAM16_TABLE = np.array([
    complex(-3*_Q16L, -3*_Q16L), complex(3*_Q16L, -3*_Q16L),
    complex(-1*_Q16L, -3*_Q16L), complex(1*_Q16L, -3*_Q16L),
    complex(-3*_Q16L, 3*_Q16L),  complex(3*_Q16L, 3*_Q16L),
    complex(-1*_Q16L, 3*_Q16L),  complex(1*_Q16L, 3*_Q16L),
    complex(-3*_Q16L, -1*_Q16L), complex(3*_Q16L, -1*_Q16L),
    complex(-1*_Q16L, -1*_Q16L), complex(1*_Q16L, -1*_Q16L),
    complex(-3*_Q16L, 1*_Q16L),  complex(3*_Q16L, 1*_Q16L),
    complex(-1*_Q16L, 1*_Q16L),  complex(1*_Q16L, 1*_Q16L),
])

_Q64L = 1.0 / np.sqrt(42)
_q64_levels = [-7, 7, -1, 1, -5, 5, -3, 3]
QAM64_TABLE = np.array([
    complex(_q64_levels[i & 7] * _Q64L, _q64_levels[(i >> 3) & 7] * _Q64L)
    for i in range(64)
])

TABLES = {1: BPSK_TABLE, 2: QPSK_TABLE, 4: QAM16_TABLE, 6: QAM64_TABLE}


def make_channel(frame_idx):
    rng = np.random.RandomState(seed=0xBEEF + frame_idx * 13)
    h = np.zeros(64, dtype=np.complex128)
    h[0] = 1.0
    h[1] = (0.3 + 0.05 * rng.randn()) * np.exp(1j * rng.uniform(0, 2 * np.pi))
    h[2] = (0.15 + 0.03 * rng.randn()) * np.exp(1j * rng.uniform(0, 2 * np.pi))
    return np.fft.fft(h)


def build_ofdm_freq(data_values, n_bpsc, symbol_idx):
    table = TABLES[n_bpsc]
    data_complex = np.array([table[v] for v in data_values])
    freq_fftshift = np.zeros(64, dtype=np.complex128)
    for i, idx in enumerate(DATA_INDICES):
        freq_fftshift[idx] = data_complex[i]
    pol = POLARITY[symbol_idx % 127]
    pilot_vals = [1, 1, 1, -1]
    for i, idx in enumerate(PILOT_INDICES):
        freq_fftshift[idx] = pol * pilot_vals[i]
    return np.fft.ifftshift(freq_fftshift)


def encode_frame(payload, mcs_name, seed):
    m = MCS[mcs_name]
    crc_val = binascii.crc32(payload) & 0xFFFFFFFF
    psdu = payload + struct.pack('<I', crc_val)
    psdu_size = len(psdu)
    n_dbps = m['n_dbps']; n_cbps = m['n_cbps']; n_bpsc = m['n_bpsc']; punct = m['punct']
    total_bits = 16 + 8 * psdu_size + 6
    n_symbols = -(-total_bits // n_dbps)
    n_data_bits = n_symbols * n_dbps
    n_pad = n_data_bits - total_bits
    all_bits = [0] * 16 + bytes_to_bits(psdu) + [0] * 6 + [0] * n_pad
    assert len(all_bits) == n_data_bits
    scrambled = scramble(all_bits, seed)
    tail_start = 16 + 8 * psdu_size
    for i in range(6):
        scrambled[tail_start + i] = 0
    coded = conv_encode(scrambled)
    punctured = puncture(coded, punct)
    assert len(punctured) == n_symbols * n_cbps
    data_syms = []
    for s in range(n_symbols):
        sym_bits = punctured[s * n_cbps:(s + 1) * n_cbps]
        inter = interleave(sym_bits, n_cbps, n_bpsc)
        vals = bits_to_values(inter, n_bpsc)
        assert len(vals) == 48
        data_syms.append(vals)
    sig_vals = encode_signal_field(m['rate_val'], psdu_size)
    return sig_vals, data_syms


def main():
    os.makedirs('/app/captures', exist_ok=True)

    frames = [
        (0, 'BPSK_1_2',  32,  0x5A),
        (1, 'QPSK_3_4',  70,  0x33),
        (2, 'QAM16_1_2', 100, 0x7F),
        (3, 'QAM64_2_3', 150, 0x42),
        (4, 'BPSK_3_4',  45,  0x1D),
    ]

    lts_ref_list = LTS_FFTSHIFT.real.tolist()

    manifest = {
        "format": "cf32_le",
        "description": "Complex float32, little-endian, interleaved I/Q pairs (I0 Q0 I1 Q1 ...)",
        "fft_size": 64,
        "samples_per_symbol": 64,
        "structure_note": "Each .iq file contains consecutive 64-sample OFDM symbols in time domain: LTS_copy1(64) + LTS_copy2(64) + SIGNAL(64) + DATA_0(64) + ... + DATA_N(64). No cyclic prefix included.",
        "lts_reference_fftshift": lts_ref_list,
        "data_subcarrier_indices_fftshift": DATA_INDICES,
        "pilot_subcarrier_indices_fftshift": PILOT_INDICES,
        "null_subcarrier_indices_fftshift": NULL_INDICES,
        "frames": {}
    }

    for idx, mcs_name, payload_size, seed in frames:
        payload = make_payload(idx, payload_size)
        sig_vals, data_syms = encode_frame(payload, mcs_name, seed)
        m = MCS[mcs_name]

        H = make_channel(idx)
        lts_natural = np.fft.ifftshift(LTS_FFTSHIFT)
        lts_ch_time = np.fft.ifft(lts_natural * H)

        samples = []
        samples.append(lts_ch_time)
        samples.append(lts_ch_time)

        sig_freq = build_ofdm_freq(sig_vals, 1, 0)
        samples.append(np.fft.ifft(sig_freq * H))

        for s, vals in enumerate(data_syms):
            data_freq = build_ofdm_freq(vals, m['n_bpsc'], s + 1)
            samples.append(np.fft.ifft(data_freq * H))

        all_samples = np.concatenate(samples)
        iq = np.zeros(2 * len(all_samples), dtype=np.float32)
        iq[0::2] = all_samples.real.astype(np.float32)
        iq[1::2] = all_samples.imag.astype(np.float32)

        filename = f"frame_{idx}.iq"
        iq.tofile(f'/app/captures/{filename}')

        manifest["frames"][f"frame_{idx}"] = {
            "file": filename,
            "n_data_symbols": len(data_syms),
            "total_samples": len(all_samples),
        }

        print(f"Frame {idx}: {mcs_name}, {payload_size}B, {len(data_syms)} data symbols, {len(all_samples)} samples")

    with open('/app/captures/manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)


if __name__ == '__main__':
    main()
