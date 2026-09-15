The NMMS specification at `/app/spec.md` defines a 3D voxel construction system where nanobots execute binary-encoded command traces (`.nbt`) to assemble target models stored as binary (`.mdl`) files. The spec covers coordinate systems, command semantics, energy accounting, the multi-bot execution model, and binary file formats.

Test case data is archived at `/app/testdata.tar.xz` (case directories each containing `target.mdl` and `trace.nbt`). A `Makefile` at `/app/Makefile` defines build targets for the tool chain. Binary format constants and macros are provided in `/app/include/nmms.h`.

Build a simulation pipeline at `/app/simulator/run.sh <model.mdl> <trace.nbt>` that outputs a single JSON object to stdout:

- `valid` (bool): whether trace execution completed without errors
- `energy` (int): total energy consumed
- `steps` (int): number of completed time steps
- `model_match` (bool): whether final voxel state matches the target model
- `error` (string or null): first error encountered, or null

The pipeline must include compiled C binary format decoders — `tools/mdl2json` and `tools/nbt2json` — with source in `/app/src/`, built via the Makefile. `mdl2json` converts `.mdl` to JSON with `resolution` (int) and `filled` (array of `[x,y,z]` triples). `nbt2json` converts `.nbt` to a JSON array of command objects with `cmd` (string) plus command-specific fields (`lld`, `sld1`/`sld2`, `nd`, `m`). The simulation engine reads the decoded JSON and implements the full NMMS execution model — multi-bot coordination, fission/fusion, grounding constraints, and energy accounting per the spec.