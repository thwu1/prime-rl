#!/usr/bin/env bash

# Copy solution source files into the task environment
cp /solution/dispersion.c /app/src/dispersion.c
cp /solution/preprocess.awk /app/preprocess.awk
cp /solution/coastal_pipeline.py /app/coastal_pipeline.py
chmod +x /app/preprocess.awk

# Generate Makefile with proper tab characters for recipes
python3 << 'PYEOF'
makefile = """.PHONY: all lib preprocess analyze clean

all: lib preprocess analyze

lib: /app/lib/libdispersion.so

/app/lib/libdispersion.so: /app/src/dispersion.c
\tmkdir -p /app/lib
\tgcc -shared -fPIC -O2 -o $@ $< -lm

preprocess:
\tmkdir -p /app/profiles
\t@for f in /app/raw_surveys/*.survey; do if [ -f "$$f" ]; then awk -f /app/preprocess.awk "$$f" > /app/profiles/$$(basename "$$f" .survey).json; fi; done

analyze:
\t@for f in /app/scenarios/*.json; do python3 /app/coastal_pipeline.py "$$f" > /dev/null; done

clean:
\trm -f /app/lib/libdispersion.so /app/results.db
\trm -rf /app/profiles
"""
with open('/app/Makefile', 'w') as f:
    f.write(makefile)
PYEOF

# Build and run the full pipeline
cd /app
make all
