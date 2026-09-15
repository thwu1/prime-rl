A server's custom package management system is in an inconsistent state after a partial upgrade was interrupted by a power failure. The package database is at `/opt/pkgdb/` with the following structure:

- `/opt/pkgdb/local/{name}-{version}/desc` — Installed package metadata (name, version, dependencies)
- `/opt/pkgdb/local/{name}-{version}/files` — File manifest listing files owned by the installed package
- `/opt/pkgdb/sync/{repo}/{name}-{version}/desc` — Repository package metadata (includes SHA256 checksums of package archives)
- `/opt/pkgdb/cache/{name}-{version}.pkg` — Cached package archive files downloaded from repositories

The metadata files use a section-based text format where each section starts with `%SECTION_NAME%` on its own line, followed by the section's values on subsequent lines. Sections are separated by blank lines. Not all sections are present in every desc file.

Write a tool to audit the entire database and detect all inconsistencies across these categories. Produce `/app/audit_report.json` containing:

**`integrity_failures`** — Cached package files whose SHA256 hash does not match the expected hash recorded in the corresponding sync database entry. Each entry: `{"package": "<name>", "version": "<ver>", "expected_sha256": "<hash>", "actual_sha256": "<hash>"}`

**`unsatisfied_dependencies`** — Installed packages with dependency constraints not satisfied by the currently installed package set. A dependency is unsatisfied if the required package is missing entirely or installed at a version that violates the constraint. Each entry: `{"package": "<name>", "version": "<ver>", "dependency": "<dep_spec>", "installed_version": "<ver_or_null>"}` (use JSON `null` when the required package is not installed at all)

**`dependency_cycles`** — Groups of installed packages forming circular dependency chains. Each entry is a list of the package names in the cycle: `["<pkg1>", "<pkg2>", ...]`

**`file_conflicts`** — Files listed in the manifests of more than one installed package. Each entry: `{"path": "<file_path>", "owners": ["<pkg1>", "<pkg2>"]}`

**`orphaned_packages`** — Package names that are installed locally but do not appear in any sync repository. List of strings: `["<name>", ...]`

Version constraints in dependencies use operators `>=`, `<=`, `>`, `<`, `=` appended directly to the package name (e.g., `libnet>=3.0.0`). Versions are dot-separated integers compared numerically component-by-component.