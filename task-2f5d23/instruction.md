A configuration file at `/app/config.json` specifies five 8-bit CRC polynomials in Koopman hexadecimal notation, CRC parameters, and analysis queries. Binary test data files are at `/app/testdata/`. The environment provides `gcc`, Python 3, and `pip3`.

## Deliverables

### 1. Compiled C shared libraries

For each polynomial, a compiled ELF shared object must exist at `/app/lib/crc_<koopman_hex>.so` (e.g., `/app/lib/crc_0xe7.so`). Each must export:

```c
unsigned char crc8_compute(const unsigned char *data, unsigned int len);
```

This function computes a CRC-8 checksum using the generator polynomial and CRC parameters (`init`, `reflect_in`, `reflect_out`, `xor_out`) from the config.

### 2. Results file

Write `/app/results.json` with this structure:

```json
{
  "profiles": {
    "<koopman_hex>": {
      "hd_profile": [P3, P4, ...],
      "has_x_plus_1_factor": true
    }
  },
  "checksums": {
    "<filename>": {
      "<koopman_hex>": <crc_value_as_integer>
    }
  },
  "cross_validation_passed": true,
  "hamming_weights": [
    {"polynomial": "<hex>", "dataword_length": 247, "error_weight": 2, "hw_value": 0}
  ]
}
```

**checksums**: CRC-8 of each file in `/app/testdata/`, computed via the compiled shared libraries. Checksum keys are bare filenames (e.g., `msg_01.bin`).

**cross_validation_passed**: `true` only if every checksum from the shared libraries has been independently verified against a separate CRC implementation that does not share code with the C libraries.

**hd_profile**: For each polynomial, a list `[P3, P4, P5, ...]` where `Pk` is the maximum dataword length (in bits, up to `max_dataword_length_bits` from the config) at which the code's Hamming Distance is at least `k`. Terminate the list when `Pk` would be zero.

**has_x_plus_1_factor**: Whether `(x+1)` divides the generator polynomial over GF(2).

**hamming_weights**: For each query in the config's `hamming_weight_queries` (same order), the exact count of undetectable error patterns of the specified weight at the specified dataword length. An error pattern of weight `w` is a selection of `w` bit positions in the codeword (dataword + CRC bits) whose corresponding error is not detected by the CRC.

Polynomial keys must use the same hex strings as the config.