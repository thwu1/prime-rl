#!/bin/bash

# Install the reference shader pipeline
cp /solution/pipeline.py /app/shader_pipeline.py
chmod +x /app/shader_pipeline.py

# Verify glslangValidator is available
if ! command -v glslangValidator &> /dev/null; then
    echo "ERROR: glslangValidator not found" >&2
    exit 1
fi

# Verify it runs and produces valid output
output=$(python3 /app/shader_pipeline.py 2>&1)
exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo "ERROR: Pipeline failed with exit code $exit_code" >&2
    echo "$output" >&2
    exit 1
fi

# Verify JSON is valid and all stages compiled
echo "$output" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for f in data['files']:
    for s in f['stages']:
        if not s['compiled']:
            print(f\"ERROR: {f['filename']}:{s['name']} failed to compile\", file=sys.stderr)
            sys.exit(1)
print(f\"Pipeline verified: {len(data['files'])} files processed, all stages compiled\")
"
