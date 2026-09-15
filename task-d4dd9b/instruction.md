A C++ project at `/app/` ("sigframe") depends on the DataFlow library. DataFlow v2 was installed from source on this system — the static library and headers are under `/usr/local/` — but the empty directory at `/usr/local/lib/cmake/DataFlow/` indicates CMake integration was never completed after the manual installation.

A previous build attempt log is at `/app/build_failure.log`. The project has not been fully updated since the DataFlow v1-to-v2 transition.

Diagnose and fix all issues preventing a successful build. The existing `find_package(DataFlow ...)` calls in the project's subdirectory CMakeLists.txt files must remain — do not bypass CMake's package discovery mechanism with hardcoded paths.

## Acceptance criteria

`cmake -B build && cmake --build build` from `/app/` succeeds, producing `/app/build/sigframe`. The binary runs successfully with output containing "Pipeline complete", "5 values", and "encoded".