A SQLite database at `/app/crc_config.db` contains 8-bit CRC polynomial specifications (in Koopman notation) and application scenarios. The `polynomials` table lists each polynomial, the `scenarios` table defines evaluation contexts, and the `config` table holds analysis parameters (`crc_width`, `max_dataword_length`, `max_hd_check`).

Binary test vector files are in `/app/test_vectors/` (see the `README` there for the packed binary format). A CRC computation utility is installed at `/app/tools/crc_util` with its source at `/app/tools/crc_util.c`.

Analyze every polynomial in the database and produce `/app/results.json`.

**Polynomial properties:**
- `explicit_plus_1`: the full polynomial in hex, with all coefficient bits present including the x^0 term
- `reciprocal_koopman`: the reciprocal polynomial expressed in Koopman notation (hex)
- `is_primitive`: whether the polynomial is primitive over GF(2)
- `has_x_plus_1_factor`: whether (x+1) divides the polynomial over GF(2)
- `hd_profile`: for each Hamming Distance level d = 3, 4, 5, ..., the maximum dataword length (bits) at which the CRC guarantees detection of all error patterns of weight up to d−1. Truncate after the last level achievable at dataword length ≥ 1. The `max_dataword_length` and `max_hd_check` parameters in the database bound the search space.

**Scenario evaluation:**
For each scenario, determine the achieved HD for each polynomial at the scenario's dataword length and whether it meets the minimum HD. Select the best qualifying polynomial: highest achieved HD, ties broken by largest margin (max dataword length at achieved HD minus target length), then smallest Koopman value.

**Output format** (`/app/results.json`):
```json
{
  "polynomials": {
    "<koopman_hex>": {
      "explicit_plus_1": "<hex>",
      "reciprocal_koopman": "<hex>",
      "is_primitive": <bool>,
      "has_x_plus_1_factor": <bool>,
      "hd_profile": [<int>, ...]
    }
  },
  "scenarios": {
    "<name>": {
      "evaluations": {
        "<koopman_hex>": {"achieved_hd": <int>, "meets_requirement": <bool>}
      },
      "best_polynomial": "<koopman_hex>"
    }
  }
}
```

All hex values lowercase with `0x` prefix.