# MixHash-24 Algorithm Specification

## Overview

MixHash-24 is a 128-bit keyed hash function using a PRNG-driven absorption phase
and a SipHash-derived mixing round. This document specifies the intended behavior
of the firmware at `/app/firmware.elf`.

## Notation

- All arithmetic is unsigned 32-bit (modulo 2^32).
- `ROTL32(x, n)` = `(x << n) | (x >> (32 - n))`, where shifts are logical (zero-fill).
- Byte order is **little-endian** throughout.

## 1. PRNG: XorShift32

A single 32-bit state variable, initialized to seed `0xDEADBEEF`.

Each call to `prng_next()`:
```
state ^= (state << 13)
state ^= (state >> 17)
state ^= (state <<  5)
return state
```

## 2. State Initialization

Four 32-bit state words:
```
v[0] = 0x736F6D65
v[1] = 0x646F7261
v[2] = 0x6C796765
v[3] = 0x74656462
```

## 3. Mixing Round (`mixround`)

One mixing round applies the following operations in order:

```
v[0] += v[1]
v[1]  = ROTL32(v[1],  5) ^ v[0]
v[2] += v[3]
v[3]  = ROTL32(v[3], 11) ^ v[2]
v[0]  = ROTL32(v[0], 16)
v[0] += v[3]
v[2] += v[1]
v[1]  = ROTL32(v[1], 13) ^ v[2]
v[3]  = ROTL32(v[3],  7) ^ v[0]
v[2]  = ROTL32(v[2], 16)
```

The six rotation constants in order are: **5, 11, 16, 13, 7, 16**.

## 4. Absorption Phase

Perform exactly **24** iterations (i = 0, 1, ..., 23):

```
r = prng_next()
v[3] ^= r
mixround(v)
mixround(v)
v[0] ^= r
```

Each iteration absorbs one PRNG value into the state via two mixing rounds.

## 5. Finalization

```
v[2] ^= 0xFF
```

Then perform exactly **3** additional mixing rounds.

## 6. Output

Emit the 4 state words `v[0], v[1], v[2], v[3]` as 16 bytes in little-endian
byte order (i.e., each word is serialized as 4 bytes, least-significant byte first).

## Memory Map

- Flash (ROM): `0x08000000` – `0x0800FFFF` (64 KB, read-only, code + constants)
- RAM: `0x20000000` – `0x20007FFF` (32 KB, read-write)

## Processor Reset

On reset, the Cortex-M4 reads from the Interrupt Vector Table (IVT) at the base
of Flash:
- `0x08000000`: Initial Stack Pointer (SP)
- `0x08000004`: Reset Handler address (bit 0 = Thumb mode indicator)

## Instruction Set

ARMv7-M Thumb-2 ISA (mixed 16-bit and 32-bit encodings). If the first halfword
has bits [15:11] in {0b11101, 0b11110, 0b11111}, it begins a 32-bit instruction.

## BKPT Syscall Convention

- **BKPT #255** (`0xBEFF`): Write syscall.
  `r0` = pointer to data buffer, `r1` = byte count. Execution continues after BKPT.

- **BKPT #0** (`0xBE00`): Halt. Execution stops.
