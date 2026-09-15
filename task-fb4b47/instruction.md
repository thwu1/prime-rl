An image processing library at `/app/src/imgutil.c` contains 5 memory safety vulnerabilities (BUG001–BUG005, one per function in declaration order). A persistent storage backend for canary data is already implemented at `/app/magma/storage.{h,c}`.

Full architecture specification and requirements are at `/app/docs/SPEC.md` and `/app/docs/REQUIREMENTS.md`.

Implement the complete ground-truth canary instrumentation system described in those documents so that fuzzer effectiveness can be precisely measured against all 5 vulnerabilities. The test driver at `/app/src/driver.c` exercises each bug with specific crafted inputs; your system must produce reached and triggered counts that exactly reflect the runtime behavior of those inputs.

Do not modify `driver.c` or `imgutil.h`.