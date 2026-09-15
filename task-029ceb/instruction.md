NVIDIA Blackwell GPUs use `tcgen05.mma` instructions for tensor core matrix multiply-accumulate. These instructions require input matrices to reside in shared memory using a specific physical layout governed by the active swizzle mode, and the hardware is configured through packed bit-field descriptors. Your task is to reverse-engineer the precise algorithms from reference data distributed across multiple formats and implement a complete, correct library.

## Provided files

- `/app/concepts.md` — High-level architectural overview of Blackwell shared memory organization, swizzle modes, descriptor fields, and TMA parameters. Describes *what* these components are and their roles, but does not give computation formulas.
- `/app/vectors.db` — SQLite database containing reference input/output pairs for address mapping and inverse mapping functions, plus a `swizzle_modes` table with chunk widths and descriptor codes. The address and inverse vector tables use foreign-key `mode_id` references rather than mode names; join with `swizzle_modes` or use the pre-built `*_named` views to correlate entries. A `descriptor_field_info` table provides partial bit-field layout hints for the 64-bit shared memory descriptor.
- `/app/descriptors/` — Directory of raw binary files: 64-bit shared memory descriptors stored as little-endian uint64 (8 bytes each) and 32-bit instruction descriptors as little-endian uint32 (4 bytes each). The file `manifest.csv` maps each binary file to its input parameters. Examine the binary content to discover how each hardware field is packed into the descriptor bit-fields.
- `/app/hw_config_dump.json` — Hardware configuration dump containing TMA (Tensor Memory Accelerator) parameter validation cases nested deep within the device capability tree. Extract the relevant test-case inputs and expected outputs to understand the 3D tensor-map parameter computation.
- `/app/tcgen05_layout.py` — Skeleton with function signatures and constant definitions.

## Goal

Complete all six functions in `/app/tcgen05_layout.py` so that:

1. The logical-to-physical address mapping is a **bijection** over all byte positions in any tile — every logical `(row, col_bytes)` maps to a unique physical offset in `[0, tile_height * tile_width_bytes)`, and the inverse function recovers the original coordinates exactly.

2. The 64-bit shared memory descriptor correctly encodes all hardware fields (base address, LBO, SBO, flag, swizzle code) for both SWIZZLE_NONE and SWIZZLE_128B modes.

3. The 32-bit instruction descriptor correctly packs data-type codes and MMA tile dimensions.

4. The 3D TMA parameters correctly reshape a K-major global matrix for transfer into the core-matrix shared memory layout across all swizzle modes.

5. The tile rearrangement function produces output consistent with the address mapping.

The test suite validates your implementation against cases that go beyond the reference data, including large-tile bijectivity checks, cross-field descriptor consistency tests, and TMA parameter verification for configurations not shown in the examples.