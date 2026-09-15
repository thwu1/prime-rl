#!/usr/bin/env bash


# Install the scheduler module
cp /solution/scheduler_impl.py /app/scheduler.py

# Install the pipeline script
cp /solution/pipeline_impl.py /app/pipeline.py

# Generate the Makefile (uses Python to ensure correct tab indentation)
python3 /solution/write_makefile.py

# Run the full pipeline
cd /app && make all
