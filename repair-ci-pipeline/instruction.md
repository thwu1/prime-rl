A Python CI log analysis library (`logminer`) at `/app/` has a failing CI pipeline after a botched migration from ad-hoc shell scripts to a Makefile + GitHub Actions setup. The migration introduced build configuration issues on top of pre-existing source code bugs.

The project has **multiple competing configuration files** for its linter and type checker — `pyproject.toml`, `setup.cfg`, `mypy.ini`, and `ruff.toml` — left behind by different contributors during the migration. These files contain conflicting settings, and some silently override the project's intended strict quality standards with lax configurations. Determining the correct, authoritative configuration for each tool requires understanding its config file resolution precedence and evaluating which settings are appropriate for the codebase's actual type safety and lint coverage needs.

A CI log from the last pre-migration run is at `/app/ci_output.log`. The current CI uses `make ci` (see `/app/Makefile`) and the GitHub Actions workflow at `/app/.github/workflows/ci.yml`.

Some tests have been quarantined (skipped or marked as expected-to-fail) based on assumptions about code behavior that may no longer hold after other bug fixes are applied. Each quarantined test must be individually evaluated — determine whether the quarantine was originally justified, whether the underlying issue has been resolved by other fixes, and whether the test should now be restored.

Diagnose and fix all issues so that:
- `make ci` runs all stages (install, lint, typecheck, test) successfully from `/app/`
- All project tests execute and pass — none skipped, none marked xfail
- The linter and type checker use the project's intended strict configuration (as defined in `pyproject.toml`), with no competing config files that silently override these settings
- The GitHub Actions workflow is valid for the project's repository structure