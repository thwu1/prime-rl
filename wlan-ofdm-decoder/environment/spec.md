# IEEE 802.11a/g OFDM PHY Layer Reference


## Frame Structure

A transmitted OFDM frame consists of:

1. **SIGNAL field** — 1 OFDM symbol (48 coded bits), always BPSK rate 1/2, no scrambling
2. **DATA field** — variable number of OFDM symbols, coded per MCS indicated in SIGNAL

## SIGNAL Field (24 information bits)

| Bits  | Field    | Description                             |
|-------|----------|-----------------------------------------|
| 0–3   | RATE     | 4-bit MCS indicator (LSB first)         |
| 4     | Reserved | 0                                       |
| 5–16  | LENGTH   | PSDU byte count, 12 bits (LSB first)    |
| 17    | PARITY   | Even parity over bits 0–16              |
| 18–23 | TAIL     | All zeros (flush convolutional encoder)  |

## DATA Field

| Component | Bits              | Description                        |
|-----------|-------------------|------------------------------------|
| SERVICE   | 16                | All zeros                          |
| PSDU      | 8 × LENGTH        | Payload bytes (LSB-first per byte) |
| TAIL      | 6                 | All zeros (flush encoder)          |
| PAD       | variable          | Zero-fill to complete last symbol  |

Total data bits per frame: `n_sym × n_dbps`

where `n_sym = ⌈(16 + 8·LENGTH + 6) / n_dbps⌉`

## MCS Table

| MCS | Modulation | Code Rate | n_bpsc | n_cbps | n_dbps | RATE field (binary) |
|-----|------------|-----------|--------|--------|--------|---------------------|
| 0   | BPSK       | 1/2       | 1      | 48     | 24     | 1011                |
| 1   | BPSK       | 3/4       | 1      | 48     | 36     | 1111                |
| 2   | QPSK       | 1/2       | 2      | 96     | 48     | 1010                |
| 3   | QPSK       | 3/4       | 2      | 96     | 72     | 1110                |
| 4   | 16-QAM     | 1/2       | 4      | 192    | 96     | 1001                |
| 5   | 16-QAM     | 3/4       | 4      | 192    | 144    | 1101                |
| 6   | 64-QAM     | 2/3       | 6      | 288    | 192    | 1000                |
| 7   | 64-QAM     | 3/4       | 6      | 288    | 216    | 1100                |

- **n_bpsc** — coded bits per subcarrier
- **n_cbps** — coded bits per OFDM symbol (= 48 × n_bpsc)
- **n_dbps** — data bits per OFDM symbol

## Convolutional Encoder

- Constraint length **K = 7** (64-state trellis, memory order 6)
- Generator polynomials (octal): **g₀ = 0155**, **g₁ = 0117**
- Base code rate: 1/2
- State update: `state ← ((state << 1) & 0x7E) | input_bit`
- Outputs: parity of `(state & g₀)` and `(state & g₁)`

## Scrambler

- LFSR polynomial: **x⁷ + x⁴ + 1**
- 7-bit state, feedback from bits 6 and 3 (XOR)
- Applied to SERVICE + PSDU + TAIL + PAD
- After scrambling, the 6 TAIL bits are reset to zero

## Puncturing

Higher code rates are achieved by periodically deleting encoded bits:

| Rate | Pattern                                                        |
|------|----------------------------------------------------------------|
| 1/2  | No bits removed                                                |
| 2/3  | Remove bit at every position *i* where `i mod 4 = 3`          |
| 3/4  | Remove bits at positions where `i mod 6 ∈ {3, 4}`             |

## Block Interleaver

A two-step permutation is applied independently to each OFDM symbol
of `n_cbps` coded bits:

    s = max(n_bpsc ÷ 2, 1)

**First permutation:**

    f(j) = s · ⌊j / s⌋ + (j + ⌊16·j / n_cbps⌋) mod s

**Second permutation:**

    g(i) = 16·i − (n_cbps − 1) · ⌊16·i / n_cbps⌋

**Encoding direction:**

    interleaved[k] = coded[ g(f(k)) ]
