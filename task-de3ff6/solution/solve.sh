#!/bin/bash

# Ensure infrastructure modules are available in /app
for f in programs.py emulator.py graph.py priority_queue.py runtime.c; do
    if [ ! -f "/app/$f" ] && [ -f "/opt/task_lib/$f" ]; then
        cp "/opt/task_lib/$f" "/app/$f"
    fi
done

cp /solution/allocator.py /app/allocator.py
cp /solution/emit.py /app/emit.py
