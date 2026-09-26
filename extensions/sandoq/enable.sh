#!/usr/bin/env bash
# Wire the sandoq extension into a recipe's prime-rl runtime.
#
#   extensions/sandoq/enable.sh <runtime_dir>      # e.g. <recipe>/.runtime/prime-rl
#
# Appends to <runtime_dir>/.env (which prime-rl's sbatch templates + the recipe run
# wrappers all `source`): puts THIS extension dir on PYTHONPATH — so `sitecustomize.py`
# auto-installs `sandoq_provider` in every process (broker, workers, trainer, inference)
# — and flips VF_SANDBOX_PROVIDER=sandoq. Configure which sandoq Environment to hit
# (SANDOQ_BASE_URL / SANDOQ_DEFAULT_ENVIRONMENT / SANDOQ_ENV_MAP) in your recipe's own
# .env. Idempotent. Call it from the recipe's install.sh after recipe_install.sh.
set -euo pipefail

EXT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RT="${1:?usage: enable.sh <runtime_dir> (e.g. <recipe>/.runtime/prime-rl)}"
ENV_FILE="$RT/.env"

[ -f "$ENV_FILE" ] || {
	echo "[sandoq] ERROR: no .env at $ENV_FILE — run the recipe's install first." >&2
	exit 1
}

MARKER="# --- sandoq extension (enable.sh) ---"
if grep -qF "$MARKER" "$ENV_FILE"; then
	echo "[sandoq] already enabled in $ENV_FILE"
	exit 0
fi

cat >>"$ENV_FILE" <<EOF

$MARKER
# Put the sandoq extension on PYTHONPATH: sitecustomize.py then auto-installs the
# provider at interpreter startup in every process, and sandoq_provider is importable.
export PYTHONPATH="$EXT_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
# Activate the provider (recipe .env may set SANDOQ_* to pick the Environment).
export VF_SANDBOX_PROVIDER="\${VF_SANDBOX_PROVIDER:-sandoq}"
EOF

echo "[sandoq] enabled -> $ENV_FILE (PYTHONPATH += $EXT_DIR ; VF_SANDBOX_PROVIDER=sandoq)"
