A stripped ELF binary at `/app/sbox_engine` implements a proprietary 8-bit S-box substitution. The binary accepts a single hex byte argument and returns `S(input)` in hex, but each evaluation incurs a 2-second constant-time delay, making brute-force extraction of all 256 values impractical within the time limit.

The S-box lookup table is embedded in the binary's read-only data section alongside other constant tables (round constants, differential profile data, license metadata, and string literals). Use ELF binary analysis tools such as `objdump`, `readelf`, `nm`, and `xxd` to locate and extract the 256-byte S-box permutation from the stripped binary. You must identify which data block in `.rodata` is the actual S-box (a permutation of 0..255) versus other constant data.

Once the S-box is extracted, decompose it as:

    S(x) = A( X( B(x) ) )

where:
- **A** and **B** are invertible 8x8 matrices over GF(2), applied to the 8-bit representation of their input (bit 0 = LSB).
- **X** is an arithmetic permutation modulo 256: `X(y) = (a * y + b) mod 256`, with `a` odd (so `gcd(a, 256) = 1`) and `0 <= b < 256`.

Write the result to `/app/answer.json`:

```json
{
  "A": [[...], ...],
  "B": [[...], ...],
  "a": <int>,
  "b": <int>
}
```

`A` and `B` are 8x8 arrays of 0s and 1s (row-major, each inner list is a row). Multiple valid decompositions may exist; any correct one will be accepted.