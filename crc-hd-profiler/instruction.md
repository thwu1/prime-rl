Five 8-bit CRC polynomials are specified in `/app/polynomials.json` using different representations: Koopman (implicit +1) hex, explicit +1 hex, and algebraic string. For each polynomial, compute its Hamming Distance profile and determine whether the generator has a factor of (x+1) over GF(2).

Write results to `/app/results.json` as a JSON object keyed by polynomial ID:

```json
{
  "P1": {
    "koopman_hex": "0x...",
    "generator_hex": "0x...",
    "hd_profile": [max_at_HD3, max_at_HD4, ...],
    "has_odd_parity": true
  }
}
```

**Field definitions:**

- `koopman_hex`: the generator polynomial in Koopman notation. In this notation, a degree-n polynomial is encoded as an n-bit value representing the coefficients of x^n through x^1, with the constant term (+1) implicit. For example, g(x) = x^8+x^7+x^6+x^3+x^2+x+1 is `0xe7` (binary 11100111 maps to coefficients of x^8..x^1).
- `generator_hex`: the full generator polynomial in explicit +1 notation (n+1 bits including both the x^n and x^0 terms).
- `hd_profile`: a list of integers. Entry at index i gives the maximum dataword length L (in bits) at which the CRC code achieves Hamming Distance >= (3+i). An n-bit CRC appends n check bits to an L-bit dataword, producing an (L+n)-bit codeword. The Hamming Distance at length L is the minimum Hamming weight among all nonzero codewords. The profile terminates when no L >= 1 achieves the next HD level.
- `has_odd_parity`: boolean, true if the generator polynomial has (x+1) as a factor over GF(2). Such polynomials detect all odd-weight error patterns.

All profile values must be exact. These are mathematical invariants of the polynomial with no approximation involved.