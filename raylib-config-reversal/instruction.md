A pre-compiled raylib static library at `/app/target/libraylib.a` was built with a
customized `config.h` — several modules and features were selectively disabled.
The unmodified raylib source tree is at `/app/raylib/` for reference.

**Part 1 — Configuration Analysis:** Determine which `config.h` compile-time flags
were enabled or disabled in the target library by analyzing its symbol table and
cross-referencing with the source code. Produce a JSON report at
`/app/analysis/config_report.json` mapping flag names to booleans (true = enabled).
Required flags to report: `SUPPORT_MODULE_RSHAPES`, `SUPPORT_MODULE_RTEXTURES`,
`SUPPORT_MODULE_RTEXT`, `SUPPORT_MODULE_RMODELS`, `SUPPORT_MODULE_RAUDIO`,
`SUPPORT_CAMERA_SYSTEM`, `SUPPORT_GESTURES_SYSTEM`, `SUPPORT_RPRAND_GENERATOR`,
`SUPPORT_SCREEN_CAPTURE`, `SUPPORT_AUTOMATION_EVENTS`, `SUPPORT_COMPRESSION_API`,
`SUPPORT_IMAGE_EXPORT`, `SUPPORT_IMAGE_GENERATION`.

Note: some public API functions exist in the library regardless of their feature
flag state (as stubs or fallback implementations). You must study the raylib source
to understand which flags control internal implementation libraries versus public
API presence, and choose detection methods accordingly.

**Part 2 — Headless Image Pipeline:** Using only functions available in the target
library, write a C program that loads `/app/input/test.png` (200x200, 4 colored
quadrants), then applies in order: grayscale conversion, 3x3 Gaussian kernel
convolution (`{0.0625, 0.125, 0.0625, 0.125, 0.25, 0.125, 0.0625, 0.125, 0.0625}`),
crop to center 100x100 at offset (50,50), vertical flip, brightness +40. Export the
result to `/app/output/result.png`. Read pixel colors at coordinates (25,25), (75,25),
(25,75), (75,75) and write them to `/app/output/report.txt` in the format specified
in `/app/spec.md`. Compile the pipeline binary to `/app/pipeline`.

Full specification and deliverable paths are in `/app/spec.md`.