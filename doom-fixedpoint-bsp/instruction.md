The multi-file C project at `/app/` implements a BSP map analyser inspired by the Doom engine. It parses a WAD binary file to extract BSP node and subsector data, then processes geometric and arithmetic queries against the tree.

**Build**: `make -C /app`
**Run**: `/app/bsp_resolver <wad_file> <query_file> <output_file>`

The project currently fails to build. Once build issues are resolved, it produces incorrect results due to bugs in the WAD parser, fixed-point math library, and BSP operations. The `DIRHASH` query has only a stub implementation that must be completed.

**WAD format**: Standard Doom WAD with a 12-byte little-endian header (4-char identification `IWAD`/`PWAD`, int32 numlumps, int32 infotableofs), followed by lump data, then a directory at `infotableofs` with 16-byte entries (int32 filepos, int32 size, char[8] name). NODES holds packed 28-byte `mapnode_t` records; SSECTORS holds 4-byte `mapsubsector_t` records. Map coordinates are converted to 16.16 fixed-point at load time. The BSP root is at index `num_nodes - 1`; leaf subsectors use `NF_SUBSECTOR` (0x8000) flag.

**Queries** (one per line, one result per line):

- `MUL a b` — 16.16 fixed-point multiply. Output: signed decimal.
- `DIV a b` — 16.16 fixed-point divide with overflow saturation matching Doom's exact semantics. Output: signed decimal.
- `HASH name` — djb2-variant lump name hash (up to 8 chars, case-insensitive). Output: unsigned decimal.
- `SIDE px py nx ny ndx ndy` — BSP partition side test. Output: 0 (front) or 1 (back).
- `ANGLE x1 y1 x2 y2` — Binary Angle Measurement via octant decomposition and slope-to-angle table lookup. Output: unsigned 32-bit BAM.
- `LOCATE x y` — BSP subsector lookup. Output: subsector index.
- `TRAVERSE x y` — Front-to-back BSP traversal. Output: comma-separated subsector indices in visitation order.
- `DIRHASH` — FNV-1a hash (32-bit, offset basis 2166136261, prime 16777619) over the loaded WAD directory. Each entry contributes 16 bytes processed byte-by-byte: filepos as 4 LE bytes, size as 4 LE bytes, name as 8 raw bytes, applied in lump order. Output: unsigned decimal.

All arithmetic uses FRACBITS=16 (FRACUNIT=65536). Fixed-point division saturates to `INT_MIN`/`INT_MAX` on overflow with sign matching the mathematical quotient. The BSP side test handles axis-aligned partitions as special cases. Angle computation uses `/app/tantoangle_lut.h`. BSP traversal visits the front subtree before the back at each node.

Verification tests all eight query types and BSP traversal ordering across hundreds of test vectors.
