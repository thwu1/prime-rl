# Qwen 2.4T recovered unfiltered trajectories v6

This package contains the certified 2,499-row canonical unfiltered Qwen
trajectory union after the exact-64 Sandoq recovery. It is not expanded into
SFT rows. The archive also carries the recovered, predecessor, superseding,
and postrun certificates needed to verify its lineage.

Verify and reconstruct with:

```bash
(cd chunks && sha256sum -c ../SHA256SUMS)
cat chunks/*.part | sha256sum
cat chunks/*.part | zstd --long=31 -t
cat chunks/*.part > qwen-2499-recovered-unfiltered-108b713af-v6.tar.zst
```

The concatenated archive must have SHA-256 `243380a12d95a8a6fc8ef21f684821b9c30117a1cc5a6e300d6247cd8267645b` and size
`140868934` bytes. See `manifest.json` for immutable input lineage.
