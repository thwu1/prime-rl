# Qwen 2.4T unfiltered trajectories

This directory contains the immutable, unexpanded trajectory streams from the
2,499-task Qwen 2.4T run and its Sandoq continuation. The pass/fail certificate
is included in the archive; no rows have been filtered or expanded for SFT.

Verify and reconstruct the archive from this directory with:

```bash
(cd chunks && sha256sum -c ../SHA256SUMS)
cat chunks/*.part | sha256sum
cat chunks/*.part | zstd -t
cat chunks/*.part > qwen-2499-unfiltered-trajectories.tar.zst
```

The concatenated archive must have SHA-256
`90c933d6066defe7de9c0c1efd3de844749915ee36af1b9226589d607ce2599c` and size
`169287831` bytes. `manifest.json` binds the two input trajectory streams, the
pass-only certificate, chunk hashes, package revision, and archive identity.
