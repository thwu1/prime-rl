A set of 5000 power consumption traces was captured from an embedded device performing AES-128-ECB encryption with a fixed unknown key. The traces are stored in a custom binary format at `/app/traces.trs`.

Recover the full 128-bit AES key using side-channel analysis.

- Trace data: `/app/traces.trs` (TRS-lite binary format)
- Format specification: `/app/format_spec.txt`
- Capture setup documentation: `/app/target_info.txt`

The raw traces are dominated by device clock harmonics and suffer from significant inter-trace timing jitter. Data-dependent power leakage from cryptographic operations is small relative to the clock baseline. Signal processing is necessary to extract the leakage signal from the noise.

Write the recovered 16-byte key as a 32-character lowercase hex string to `/app/recovered_key.hex`.