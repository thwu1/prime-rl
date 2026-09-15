#!/bin/bash

# Install the GDL reasoner implementation
cp /solution/gdl_reasoner_impl.py /app/gdl_reasoner.py 2>/dev/null || true

# Verify installation
if [ ! -f /app/gdl_reasoner.py ]; then
    echo "Primary copy failed, trying python3 fallback" >&2
    python3 -c "
import shutil
shutil.copy2('/solution/gdl_reasoner_impl.py', '/app/gdl_reasoner.py')
" 2>&1
fi

# Smoke test
python3 /app/gdl_reasoner.py /app/games/maze.kif roles
