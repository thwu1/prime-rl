# Key Validation Algorithm

The bytecode must implement the following key-group validation algorithm.

## Memory Layout (pre-initialised by the caller)

| Slot   | Contents                          |
|--------|-----------------------------------|
| mem[0] | seed (32-bit unsigned integer)    |
| mem[1] | key_group[0]                      |
| mem[2] | key_group[1]                      |
| mem[3] | key_group[2]                      |
| mem[4] | key_group[3]                      |
| mem[5] | key_group[4]                      |
| mem[6–7] | available for temporary storage |
| mem[8+] | unused / available              |

## Constants

```
MAGIC    = [0xA5B4C3D2, 0x1F2E3D4C, 0x9A8B7C6D, 0x5E4F3A2B, 0xD1C2B3A4]
PRIMES   = [0x01000193, 0x811C9DC5, 0xC4CEB9FE, 0x13375EED, 0xDEADC0DE]
ROUND2   = [0x85EBCA6B, 0xC2B2AE35, 0x7FEB352D, 0x846CA68B, 0x9E3779B9]
MURMUR   = 0x5BD1E995
FINALIZE = 0x1B873593
```

## Procedure

For each group index **i** from 0 to 4:

1. **Compute expected value** from current seed:
   ```
   val  = seed XOR MAGIC[i]
   val  = val * PRIMES[i]              (mod 2^32)
   val  = ROTR(val, 13)
   val  = val XOR (val >> 16)
   val  = (val + ROUND2[i]) XOR seed   (mod 2^32, addition first)
   val  = ROTL(val, 7)
   val  = val * MURMUR                 (mod 2^32)
   val  = val XOR (val >> 15)
   ```

2. **Compare**: if `key_group[i] != val` → **HALT with result 1** (reject).

3. **Update seed** for the next iteration:
   ```
   seed = seed XOR key_group[i]
   seed = seed + MAGIC[i]              (mod 2^32)
   seed = ROTR(seed, 11)
   seed = seed * FINALIZE              (mod 2^32)
   ```

After all 5 groups pass: **HALT with result 0** (accept).

## Notes

- All values are unsigned 32-bit integers; all arithmetic wraps at 2^32.
- ROTR(x, n) = (x >> n) | (x << (32 − n)), for 0 < n < 32.
- ROTL(x, n) = (x << n) | (x >> (32 − n)), for 0 < n < 32.
- The seed is chained: each group's key value feeds into the seed for the next group, so the validation is order-dependent.
