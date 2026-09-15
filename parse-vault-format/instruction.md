A binary archive at `/app/archive.vault` uses an undocumented proprietary container format. Partial format documentation is available at `/app/FORMAT_NOTES.txt`, but the encryption algorithms are redacted.

The original vault creation tool exists as a stripped ELF binary at `/app/vault_tool`. This binary implements both the file data encryption and metadata encryption algorithms used by the format. It has no symbols, no help text, and no source code. You must reverse engineer the encryption logic from the binary using the pre-installed disassembly and analysis tools (`radare2`, `binwalk`, `objdump`, `xxd`, `strings`, `file`).

The file encryption and metadata encryption use **different** PRNG-based stream cipher algorithms with different key derivation schemes. Both must be reverse engineered from the `vault_tool` binary's machine code.

Write a self-contained Python parser at `/app/vault_parser.py` (standard library only, no dependency on `vault_tool`) that accepts two arguments: an input vault file path and an output directory path. When executed as:

```
python3 /app/vault_parser.py /app/archive.vault /app/results
```

It must produce:

- `/app/results/file_table.json` — JSON array of all file entries. Each entry must include: `name`, `compressed_size`, `decompressed_size`, `crc32` (hex string like `"0xABCD1234"`), `flags` (integer), `encrypted` (boolean), and `sha256` (hex string of the plaintext content's SHA-256).
- `/app/results/extracted/<filename>` — All extracted files in their original plaintext form, with CRC32 integrity verified.
- `/app/results/metadata.json` — The decrypted metadata section as JSON.
- `/app/results/verification.txt` — The `verification_token` string from the decrypted metadata.
- `/app/results/integrity.txt` — The `integrity_hash` string from the decrypted metadata.

The parser must be general-purpose — it must work on any well-formed vault file using this format, not just the specific archive provided. A second vault file at `/app/test_extra.vault` (different content, different seed) will also be tested.