Disk images at `/app/images/` are protected with Linux dm-verity integrity verification. A manifest at `/app/manifest.json` provides each image's filename and the byte offset where its verity metadata area begins. No other metadata is provided — all cryptographic parameters must be extracted directly from the on-disk binary structures within each image.

The images use heterogeneous configurations — different hash algorithms and different hash block sizes. Some images have had specific data blocks tampered with after their verity hash trees were generated. The hash trees themselves remain intact.

## Part 1: Forensic Analysis Tool

Build `/app/verity_forensics.py` that processes every image in the manifest and writes `/app/report.json`:

```json
{
  "images": {
    "<filename>": {
      "root_hash": "<hex lowercase>",
      "hash_algorithm": "<algorithm name as stored in verity metadata>",
      "integrity": "clean" | "corrupted",
      "corrupted_data_blocks": [<int>, ...]
    }
  }
}
```

- Root hashes must be derived from on-disk hash tree structures — they are not stored in the manifest or provided elsewhere.
- `corrupted_data_blocks` must list 0-based data block indices, sorted ascending.
- The forensic tool must implement all cryptographic operations and tree traversal natively in Python without shelling out to `veritysetup` or other binaries.

## Part 2: Remediation Script

Create `/app/remediate.sh` — a Bash script that rebuilds the verity hash tree for each corrupted image identified in Part 1 using `veritysetup format`, preserving each image's original cryptographic parameters (algorithm, salt, block sizes). After running the script, `veritysetup verify` must succeed on every previously-corrupted image.

The script must write `/app/remediation.json` mapping each remediated image filename to its new root hash (hex lowercase).

`veritysetup` and standard Linux utilities are available in the environment.