Build a compiled C program at `/app/xv6-fsck` that detects structural inconsistencies in xv6 filesystem images. The binary must be an ELF executable built by running `make` in `/app` — a Makefile skeleton at `/app/Makefile` has missing build rule(s) you must add.

## Provided resources

- `/app/fs_spec.h` — xv6 on-disk format specification (a valid C header you may `#include`)
- `/app/reference.img` — a known-consistent filesystem image (zero errors expected)
- `/app/corrupted/` — seven corrupted filesystem images (`sample_a.img` through `sample_g.img`), each containing one or more structural inconsistencies
- `/app/error_types.json` — output schema listing the six error type names and their required JSON fields

## Task

Determine what consistency invariant each of the six error types represents by analyzing the corrupted images against the reference image and the format specification. Use binary inspection tools (`xxd`, `hexdump`) to identify on-disk differences between the corrupted and reference images, then reason about which filesystem invariant each difference violates. The type names and field schemas in `error_types.json` define *what* to output — you must reverse-engineer the detection semantics from the provided samples and the format spec.

Implement a C program that performs all six consistency checks. It takes a single argument (filesystem image path) and writes a JSON report to stdout:

```json
{"errors": [{"type": "ERROR_TYPE", ...fields per error_types.json...}]}
```

A consistent image must produce an empty errors list. The `inodes` fields (where present) must be sorted ascending.

The checker must correctly handle both direct block pointers (`addrs[0..11]`) and the single indirect block (`addrs[12]`, pointing to a block of up to 256 `uint32` data-block pointers). Block address 0 means "unallocated" and should be skipped. The indirect block itself counts as a referenced block.