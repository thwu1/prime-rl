# Division Unit Lookup Table — Format Specification

## Overview

This directory contains data extracted from a processor's floating-point division unit. The processor uses a hardware lookup table to accelerate iterative division. A manufacturing run shipped with a defective lookup table that produces incorrect results for certain floating-point divisions.

Two representations of the lookup table are provided: a raw binary ROM dump from the **defective** chip, and a PLA (Programmable Logic Array) specification from the **corrected** chip revision.

## Table Dimensions

The lookup table contains **2048 entries** organized as a 16 × 128 grid:

- **Columns (16)**: Indexed by `d_idx` (0–15), representing a truncated floating-point divisor `d = 1 + d_idx/16`. The divisor is always normalized to `[1.0, 2.0)`.

- **Rows (128)**: Indexed by `p_idx` (−64 to +63), representing a truncated partial remainder `p = p_idx/8`. The truncation uses floor toward negative infinity.

- **Entry value**: A signed integer `q ∈ {−2, −1, 0, +1, +2}` — the quotient digit selected for that `(d, p)` combination.

## Binary ROM Format (`buggy_rom.bin`)

- **Size**: 2048 bytes exactly.
- **Encoding**: Each byte is a signed 8-bit integer (`0xFE` = −2, `0xFF` = −1, `0x00` = 0, `0x01` = +1, `0x02` = +2).
- **Layout**: `d_idx` varies slowest (blocks of 128 bytes). Within each block, bytes are ordered by the 7-bit two's complement hardware address of `p_idx`:
  - Bytes 0–63 correspond to `p_idx` = 0 through 63
  - Bytes 64–127 correspond to `p_idx` = −64 through −1
- **Address formula**: `byte_offset = d_idx × 128 + (p_idx mod 128)` where `mod` maps negative values to the range 64–127 (i.e., `−64 mod 128 = 64`, `−1 mod 128 = 127`).

## PLA Format (`fixed_rom.pla`)

The file uses the Berkeley/Espresso PLA format:

- **11 inputs**: `d3 d2 d1 d0` (4-bit divisor index, MSB first) and `p6 p5 p4 p3 p2 p1 p0` (7-bit partial remainder index in two's complement, MSB = sign bit).
- **2 outputs**: `mag1 mag2` — quotient digit magnitude flags:
  - `mag1=1, mag2=0` → |q| = 1
  - `mag1=0, mag2=1` → |q| = 2
  - Both 0 → q = 0
- **Sign convention**: The sign of q matches the sign of the partial remainder. For `p_idx ≥ 0`, q is positive; for `p_idx < 0`, q is negative.

Each PLA row is a product term. The input pattern uses: `1` (bit must be 1), `0` (bit must be 0), `-` (don't care). A row's output is asserted when the input matches all non-don't-care positions. The final output for a given input is the OR of all matching rows' outputs.

## Division Algorithm Context

The lookup table is part of an iterative base-4 hardware divider. The division proceeds as follows:

1. Initialize the partial remainder `w₀` to the dividend significand `a` (in `[1.0, 2.0)`).
2. Compute the divisor index `d_idx = floor((d − 1) × 16)` from divisor `d` (in `[1.0, 2.0)`).
3. At each iteration step:
   - Truncate `w` to get `p_idx = floor(w × 8)`, clamped to `[−64, 63]`.
   - Look up quotient digit `q` from table at `(d_idx, p_idx)`.
   - Update: `w ← 4 × (w − q × d)`.
4. Accumulate quotient: `Q = q₁ + q₂/4 + q₃/16 + …`

Entries with `q = 0` in the outer regions of the table (large `|p|`) represent input combinations that should never occur during convergent division. If the algorithm accesses such an entry due to a table error, the partial remainder grows uncontrollably, corrupting the quotient.
