#!/bin/bash

set -euo pipefail

: "${SETUP_ROOT:?Set SETUP_ROOT}"

readonly asset_dir=/storage/home/tianhaowu/prime-rl/user/tianhaowu/swebench_vmvm/openhands_sdk_harness
readonly portable_python=/storage/home/tianhaowu/.ocrun-portable/python/cpython-3.12.13-linux-x86_64-gnu
readonly python_dir="$SETUP_ROOT/python"
readonly venv_dir="$SETUP_ROOT/.venv"
readonly archive="$SETUP_ROOT/openhands-sdk-1.17.0.tar.zst"

mkdir -p "$SETUP_ROOT"

if [ ! -x "$portable_python/bin/python3.12" ]; then
    echo "Validated portable Python is missing: $portable_python" >&2
    exit 1
fi

if [ ! -x "$python_dir/bin/python3.12" ]; then
    rm -rf "$python_dir"
    mkdir -p "$python_dir"
    cp -a "$portable_python/." "$python_dir/"
fi

rm -rf "$venv_dir"
"$python_dir/bin/python3.12" -m venv "$venv_dir"
target_site="$venv_dir/lib/python3.12/site-packages"
source_site=$(LMNR_DISABLE_TRACING=true OPENHANDS_SUPPRESS_BANNER=1 uv run --offline \
    --python "$portable_python/bin/python3.12" \
    --with openhands-sdk==1.17.0 \
    --with openhands-tools==1.17.0 \
    python -c 'import importlib.util, pathlib; spec = importlib.util.find_spec("openhands"); print(pathlib.Path(next(iter(spec.submodule_search_locations))).parent)')
test -d "$source_site/openhands"
test -d "$source_site/openhands_sdk-1.17.0.dist-info"
test -d "$source_site/openhands_tools-1.17.0.dist-info"
cp -a "$source_site/." "$target_site/"

LMNR_DISABLE_TRACING=true OPENHANDS_SUPPRESS_BANNER=1 "$venv_dir/bin/python" "$asset_dir/patch_sdk.py" \
    --venv "$venv_dir" \
    --manifest "$SETUP_ROOT/manifest.json"
LMNR_DISABLE_TRACING=true OPENHANDS_SUPPRESS_BANNER=1 "$venv_dir/bin/python" - <<'PY'
import importlib.metadata
from openhands.sdk import Agent, Conversation, LLM, Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool

assert importlib.metadata.version("openhands-sdk") == "1.17.0"
assert importlib.metadata.version("openhands-tools") == "1.17.0"
assert all((Agent, Conversation, LLM, Tool, FileEditorTool, TaskTrackerTool, TerminalTool))
PY

rm -rf "$python_dir/conda-meta/history"
find "$venv_dir" "$python_dir" -type d -name __pycache__ -prune -exec rm -rf {} +

cd "$SETUP_ROOT"
tar --zstd -cf "$archive.tmp" python .venv manifest.json
mv "$archive.tmp" "$archive"
sha256sum "$archive" > "$archive.sha256"
du -h "$archive"
du -sh "$SETUP_ROOT"
