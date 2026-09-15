An embedded encryption device uses a secret 16-byte key. Pre-captured power consumption measurements from the device's encryption operations are stored at `/app/captures/traces.h5` (HDF5 format with nested group structure). An intercepted encrypted message is at `/app/captures/intercept.h5`.

The device firmware source code is at `/app/device_src/xxtea_xor.c`. A security audit report describing the device's encryption pipeline and identified side-channel vulnerability is at `/app/device_spec.txt`.

Recover the device's secret key by exploiting the power consumption side-channel in the captured traces. Use the recovered key to decrypt the intercepted message.

## Output Requirements

1. Write the recovered 16-byte key as exactly 32 lowercase hex characters (no prefix, no whitespace) to `/app/recovered_key.hex`.

2. Decrypt the intercepted ciphertext using the recovered key following the device's decryption pipeline (XXTEA decrypt, then reverse XOR preprocessing in reverse order i=15..0). The decrypted plaintext is a 24-character printable ASCII string in the format `esc{...}` (starts with `esc{`, ends with `}`). Write this plaintext exactly to `/app/flag.txt`.

3. The content of `/app/flag.txt` must exactly match the result of decrypting the ciphertext from `/app/captures/intercept.h5` (dataset `payload/encrypted_blocks`) with the key from `/app/recovered_key.hex`. The key must be the genuine key recovered from the power traces — it must produce statistically significant Hamming-weight correlation with the trace data at the expected operation points.