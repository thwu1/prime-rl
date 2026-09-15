#!/bin/bash

# Ensure terminal.py is accessible in /app/
cp /opt/task_lib/terminal.py /app/terminal.py 2>/dev/null || true

export PYTHONPATH="/app:/opt/task_lib:${PYTHONPATH}"
export TERM=xterm-256color

# Copy the solution into place
cp /solution/diff_impl.py /app/diff_engine.py
cp /solution/tmux_impl.py /app/tmux_validator.py
