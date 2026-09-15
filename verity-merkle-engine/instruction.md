Build `/app/verity_forensics.py` — a Python tool that performs offline forensic analysis of dm-verity protected volumes by parsing raw on-disk binary structures, independently verifying Merkle hash trees, and synthesizing kernel activation parameters.

The tool must implement three subcommands:

## `parse`

Read the 512-byte dm-verity superblock from a hash device image and output a JSON object to stdout containing: `version`, `hash_type`, `uuid` (dash-separated RFC 4122), `algorithm`, `data_block_size`, `hash_block_size`, `data_blocks`, `salt_size`, `salt` (lowercase hex). Args: `--hash <path>`, `--hash-offset <bytes>` (default 0). On invalid superblock, print `INVALID_SUPERBLOCK` to stderr and exit 1.

## `audit`

Independently recompute the full Merkle hash tree from raw data blocks and compare against the stored tree to identify corrupted blocks. Args: `--data <path>`, `--hash <path>`, `--hash-offset <bytes>` (default 0). Output JSON to stdout: `root_hash` (lowercase hex), `algorithm`, `data_blocks`, `tree_valid` (boolean), `corrupted_blocks` (sorted zero-indexed list), `corruption_pct` (float percentage). Data and hash may reside in the same file when hash is appended at an offset.

## `dm-table`

Generate a device-mapper target table line for `dmsetup create --table`. Args: same as `audit` plus `--data-dev <string>` and `--hash-dev <string>`. Parse the superblock, compute the root hash, and print the 13-field dm-verity kernel target table line to stdout.

## Environment

Hash images use the standard on-disk format produced by `veritysetup format` (with superblock). The tools `veritysetup` and `dmsetup` are installed at `/usr/sbin/` for experimentation. A sample 4MB data image is at `/app/sample/data.img`.