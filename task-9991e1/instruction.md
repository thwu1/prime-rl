The directory `/app/cipher_impl/` contains materials from a security audit of the SIGMA-256 block cipher. The cipher's substitution layer uses four 8-bit S-boxes (T0 through T3). The compiled substitution tables are in the ELF object file `/app/cipher_impl/sbox.o`; the header `/app/cipher_impl/sbox.h` declares the symbols. The original C source has been removed.

Review `/app/cipher_impl/audit_note.txt` for the audit context and findings. One of the four S-boxes has a structural vulnerability — it can be decomposed into simpler algebraic components that would compromise the cipher's security.

Your job: identify the vulnerable S-box, analyze and recover its decomposition, and write your findings to `/app/findings.json` in this format:

```json
{
  "weak_sbox_id": <int: table index 0-3>,
  "decomposition": {
    "A": <8x8 array of 0s and 1s, row-major>,
    "B": <8x8 array of 0s and 1s, row-major>,
    "a": <odd integer 1-255>,
    "b": <integer 0-255>
  }
}
```

The decomposition must satisfy `S(x) = A( f( B(x) ) )` for all x in {0,...,255}, where `A` and `B` are invertible 8x8 GF(2) matrices applied as bit-linear maps (LSB-first bit ordering: integer x maps to bits [x0,...,x7] with x = x0 + 2*x1 + ... + 128*x7), and `f(y) = (a*y + b) mod 256`.