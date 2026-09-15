Complete the implementation of `/app/mseed3pack.c` so that it produces a valid miniSEED v3 binary record at `/app/output.mseed3` containing 400 Steim2-compressed seismological samples.

The program must compile with `make` in `/app` and exit 0 when run as `./mseed3pack`.

**Required output record properties:**

- Bytes 0-1: record indicator `MS` (ASCII 0x4D, 0x53)
- Byte 2: format version `3`
- Byte 15: data encoding identifies Steim2 compression
- Bytes 28-31: CRC-32C (Castagnoli) computed over the full record with the CRC field zero-filled
- Source identifier, sample rate, sample count, and timestamp fields consistent with the constants defined in the source file
- Record size equals 40 + SID length + extra headers length + data payload length

**Steim2 payload requirements:**

- Encoded payload round-trips to 400 integer samples matching `(int32_t)dsinedata[i]` for `i` in `[0, 400)`
- Forward integration constant X0 (frame 0, word 1) equals the first encoded sample
- Reverse integration constant Xn (frame 0, word 2) equals the last decoded sample
- All seven Steim2 packing modes (7x4-bit through 1x30-bit) must be used; the expanding-sinusoid test data exercises all of them

The format specification in `/app/mseedformat.h` documents the v3 fixed header layout, CRC-32C algorithm, and Steim2 frame structure including the packing mode table with bit positions, nibble codes, and decode nibble values.

**Verification:** `make && ./mseed3pack` must exit 0 and produce `output.mseed3` passing all pytest checks.
