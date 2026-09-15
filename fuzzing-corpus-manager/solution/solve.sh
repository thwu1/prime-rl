#!/bin/bash


# Restore skeleton structure from persistent backup (handles case where /app was wiped)
mkdir -p /app/fuzzcorp
cp -a /opt/skeleton/. /app/

# Overlay correct implementations onto the stubs
cp /solution/coverage_impl.py /app/fuzzcorp/coverage.py
cp /solution/corpus_impl.py /app/fuzzcorp/corpus.py
cp /solution/scheduler_impl.py /app/fuzzcorp/scheduler.py
