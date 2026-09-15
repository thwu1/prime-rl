A custom binary archive is located at `/app/artifact.bin`. This file uses an undocumented proprietary container format that bundles multiple files together with compression and selective encryption. No format specification or tooling exists for this format.

Reverse engineer the archive format, extract all embedded files, decrypt any encrypted entries, and parse any nested data structures found within the extracted files.

Write the following outputs to `/app/output/`:

- `token.txt` — the security token hidden within a nested structure inside an encrypted archive entry (exact string, no trailing whitespace)
- `manifest.json` — JSON object with keys: `num_files` (integer count of files in the archive), `file_names` (sorted array of all filename strings as stored in the archive), `encrypted_count` (integer count of entries that were encrypted)
- `credentials.txt` — the full decrypted text contents of the credentials file found in the archive