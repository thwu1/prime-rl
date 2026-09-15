The ESP32 TWAI (Two-Wire Automotive Interface) controller uses a hardware acceptance filter for CAN bus frames, configured via an 8-byte register block: 4 bytes acceptance code + 4 bytes acceptance mask, big-endian. The register mask polarity and bit-field layout for each mode must be reverse-engineered from the Rust HAL source at `/app/reference/twai_filter.rs`.

Four filter modes exist:

- **single_standard**: 11-bit standard ID, RTR bit, first two data bytes.
- **single_extended**: 29-bit extended ID, RTR bit.
- **dual_standard**: Two sub-filters (accept if either matches). Sub-filter 1: standard ID + RTR + one data byte (split across non-contiguous nibble positions). Sub-filter 2: standard ID + RTR.
- **dual_extended**: Two sub-filters matching partial 29-bit extended IDs.

Build `/app/twai_filter.py` supporting three CLI operations:

**match** — `python3 /app/twai_filter.py match <mode> <reg_hex> <frame_spec>` where `reg_hex` is 16 hex chars (8 register bytes) and `frame_spec` is `<std|ext>:<id_hex>:<rtr>:<payload_hex>` (rtr is 0/1, payload may be empty). Print `ACCEPT` or `REJECT`. Missing payload bytes are treated as `0x00`.

**synthesize** — `python3 /app/twai_filter.py synthesize <mode> <frame_spec> [...]` computes the most selective register configuration accepting all given frames while minimizing don't-care mask bits. For dual modes, optimally partition frames across sub-filters. Print the 16-char lowercase hex register string.

**parse-dump** — `python3 /app/twai_filter.py parse-dump <path>` parses a binary register dump. Format: 4-byte ASCII magic `TWAI`, little-endian `uint16` entry count, then per entry: `uint8` mode enum (0–3 mapping to the four modes in order), 8 bytes register data, `uint8` label length, then ASCII label bytes. Print a JSON array of objects with `"mode"`, `"reg_hex"`, and `"label"` fields.

Additional reference material: test vectors at `/app/test_vectors.json`, binary dump at `/app/reference/register_configs.bin`.