`/app/builds/` contains 8 subdirectories, each representing a failed Docker build for a project in a different programming language (Python, Go, Rust, C++, Node.js, Ruby, PHP, Java). Each subdirectory has:
- `build.log` — Docker build output showing the failure
- `Dockerfile.broken` — the Dockerfile that failed
- `manifest.json` — project metadata including dependencies and build system

Additionally, `/app/package_db.json` provides an incomplete mapping from common library names to apt package names, and `/app/schema.json` defines the expected output schema.

Your task: build an automated triage pipeline that analyzes these build failures and produces corrected Dockerfiles.

Produce the following outputs:

1. **`/app/triage.py`** — A Python script that, when executed (`python3 /app/triage.py`), reads all build data from `/app/builds/`, analyzes each failure, and writes:
   - A corrected `Dockerfile.fixed` into each build subdirectory
   - A structured report to `/app/report.json`

2. **`/app/builds/<name>/Dockerfile.fixed`** — Corrected Dockerfile for each build. Each must be a valid Dockerfile that resolves the build failure identified in the corresponding `build.log`. Fixes must address root causes, not symptoms — e.g., distinguishing runtime packages from `-dev` header packages, identifying when a base image version is too old for the required language features, recognizing when environment variables disable required build functionality, and knowing when language-specific extension installation commands (like `docker-php-ext-install`) are needed beyond just installing system libraries.

3. **`/app/report.json`** — A JSON report conforming to `/app/schema.json` containing:
   - Per-build analysis with failure categories (from the enum in the schema), root cause descriptions, applied fixes, system packages added, base image changes, and environment variable changes
   - A summary with total builds, failure distribution across categories, and total unique system packages needed

The triage script must be re-runnable: executing `python3 /app/triage.py` should regenerate all outputs from the build data.