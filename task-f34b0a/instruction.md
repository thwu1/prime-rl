The directory `/app/` contains a posit16 (16-bit, es=1) arithmetic library with a CMake build system. The project should produce a shared library `libposit16.so` and an executable `test_driver` that links against it.

The CMake build currently fails with multiple errors spanning configuration, compilation, and linking. Diagnose and fix all issues in `CMakeLists.txt` so that both `libposit16.so` and `test_driver` are produced under `/app/build/`. The `test_driver` binary must resolve `libposit16.so` at runtime without relying on `LD_LIBRARY_PATH`.

Once the build succeeds, the following arithmetic operations in `posit16.c` produce incorrect or missing results:

- `p16_mul` — returns wrong values for certain input pairs
- `p16_div` — unimplemented
- `q16_fdp_add` — unimplemented
- `q16_to_p16` — unimplemented

Fix all four to conform to the Posit Standard (2022): NaR (`0x8000`) propagation, zero-preservation, round-to-nearest-even with correct tie-breaking, and regime-boundary saturation. The 128-bit quire (`quire16_t`) accumulates exact products without intermediate rounding; `q16_to_p16` converts back to posit16 with a single rounding step.

The working functions (`p16_to_f64`, `p16_add`, `p16_sub`) and the type definitions in `posit16.h` demonstrate the codebase's encoding conventions and rounding patterns.

Tests expect `/app/build/test_driver` and `/app/build/libposit16.so` to exist with all API symbols exported.

Verify: `python3 -m pytest /tests/test_state.py -v`
