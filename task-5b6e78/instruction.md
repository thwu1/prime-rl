The directory `/app/` contains a TOML manifest (`/app/manifest.toml`) describing five pairing-friendly elliptic curves from the BN and BLS12 families. Curve parameters are stored in heterogeneous formats referenced by the manifest:

- **PARI/GP scripts** (`.gp` files in `/app/params/`): executable with the `gp` interpreter; output computed parameter values
- **Hex files** (`.hex` files in `/app/params/`): hexadecimal integer encodings
- **Inline values**: some parameters appear directly in the TOML manifest

Some of these curves contain deliberate errors — corrupted parameters, inflated security claims, or polynomial inconsistencies.

Your goal is to produce two output files:

**`/app/results.json`** — a structured audit report covering all five curves:
```json
{
  "curves": [
    {
      "name": "curve_name",
      "valid": true,
      "validation_errors": [],
      "g1_security_bits": 123.45,
      "gt_security_bits": 145.67,
      "overall_security_bits": 123.45,
      "meets_claimed_level": false
    }
  ]
}
```

Each curve entry must contain:
- `valid`: whether the curve's seed `u`, field prime `p`, and group order `r` are consistent with the named family's construction polynomials, `p` and `r` are both prime, and the embedding degree `k` is correct and minimal.
- `validation_errors`: list of strings describing any failures (empty if valid).
- `g1_security_bits`: estimated security (bits) against discrete-log attacks in the base-field group G1; `null` if invalid.
- `gt_security_bits`: estimated security (bits) in the extension-field target group GT, accounting for state-of-the-art NFS variants including tower decomposition attacks; `null` if invalid.
- `overall_security_bits`: `min(g1, gt)`; `null` if invalid.
- `meets_claimed_level`: `true` when `floor(overall_security_bits) >= claimed_security_bits` from the manifest; `false` otherwise (always `false` for invalid curves).

**`/app/verify.gp`** — a PARI/GP script that independently verifies primality and polynomial consistency for every curve. When executed via `gp -q /app/verify.gp`, it must print one colon-delimited line per check: `curve_name:check_name:result` where result is `1` (pass) or `0` (fail). Required checks per curve: `p_prime`, `r_prime`, `poly_consistent`.