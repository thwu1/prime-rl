The C project at `/app/` (`netdaemon`) provides shared libraries (`libndcore`, `libndcrypto`) and tools (`ndcli`, `ndserver`) for network daemon management. A v3.0.0 migration was started but abandoned mid-way, leaving the build system, source code, and distribution metadata in an inconsistent state. The cmake configuration currently fails entirely.

A previous developer's migration notes are at `/app/docs/MIGRATION_PLAN.md`. The project's ABI version policy is documented at `/app/docs/ABI_POLICY.md`. These documents contradict each other and sometimes conflict with the actual source code. Where the migration notes disagree with the code or ABI policy, they are wrong — evaluate and disregard incorrect claims rather than implementing them.

Deliver a release-ready project where:

- The project configures, compiles, links, and installs cleanly via cmake
- SOVERSION is set correctly per the ABI version policy in `ABI_POLICY.md`
- Both shared libraries use GNU ld version scripts (`.map` files) that export only public API symbols declared in their respective headers, hiding all internal functions from the dynamic symbol table
- The installed `pkg-config` `.pc` file accurately describes the v3.0.0 libraries with correct link flags
- The systemd service unit under `pkg/` reflects the actual server binary's runtime behavior
- Distribution package manifests under `pkg/manifests/` are conflict-free across sub-packages
- A complete cmake config-mode package is designed and implemented from scratch: downstream consumers must be able to `find_package(netdaemon REQUIRED)` and link against namespaced targets `netdaemon::ndcore` and `netdaemon::ndcrypto` with correct transitive dependency propagation and a version compatibility file

The `VERSION` file and public headers in `src/` are the authoritative references for the project version and API surface.