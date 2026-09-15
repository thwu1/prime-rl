Analyze five CRC-8 polynomials given in Koopman notation. Polynomial specifications are in `/app/polynomials.json`. Test vector data is encoded in the custom binary file `/app/test_data.bin` (format documented in `/app/FORMAT.md`); use `xxd` and the format specification to extract the test vectors. A C-based CRC-8 computation engine source is at `/app/crc_engine.c` with an accompanying `/app/Makefile` — compile it with `make` and use the resulting `./crc_engine` binary to cross-validate your CRC computations.

In Koopman notation, the n-bit value encodes polynomial coefficients x^n through x^1, with the x^0 = 1 term implicit.

For each polynomial, compute and write to `/app/results.json`:

- `standard_hex`: full 9-bit generator polynomial as lowercase `0x`-prefixed hex (e.g., Koopman `0xe7` → `0x1cf`)
- `is_irreducible`: boolean — whether the standard-form polynomial is irreducible over GF(2)
- `is_primitive`: boolean — irreducible with maximal period 2^8 − 1 = 255
- `has_x_plus_1_factor`: boolean — whether (x+1) divides the standard-form polynomial
- `factor_degrees`: sorted list of degrees of irreducible factors over GF(2) (with multiplicity)
- `period`: multiplicative order of x in GF(2)[x]/P(x) — smallest k > 0 such that x^k ≡ 1 (mod P(x))
- `max_dataword_hd3`: maximum dataword length (bits) guaranteeing Hamming Distance ≥ 3
- `max_dataword_hd4`: maximum dataword length (bits) guaranteeing HD ≥ 4; 0 if never achieved
- `crc_alpha`: integer CRC-8 for test vector "alpha" (extracted from `/app/test_data.bin`)
- `crc_bravo`: integer CRC-8 for test vector "bravo"
- `crc_charlie`: integer CRC-8 for test vector "charlie"
- `crc_c_validated`: boolean — `true` if CRC values from the compiled C engine match the above

CRC-8 parameters: MSB-first bit processing, init=0, no output XOR, no input/output reflection. Dataword length = message bits; codeword = dataword + 8.

Also include `best_hd4_polynomial`: Koopman hex key of the polynomial with the highest `max_dataword_hd4` (ties broken by lower Koopman hex value).

Required output format for `/app/results.json`:
```json
{
  "polynomials": {
    "0xNN": {
      "standard_hex": "0xNNN",
      "is_irreducible": false,
      "is_primitive": false,
      "has_x_plus_1_factor": false,
      "factor_degrees": [1, 7],
      "period": 0,
      "max_dataword_hd3": 0,
      "max_dataword_hd4": 0,
      "crc_alpha": 0,
      "crc_bravo": 0,
      "crc_charlie": 0,
      "crc_c_validated": true
    }
  },
  "best_hd4_polynomial": "0xNN"
}
```

All hex strings must be lowercase with `0x` prefix. Every polynomial from the input must appear as a key in `"polynomials"`.