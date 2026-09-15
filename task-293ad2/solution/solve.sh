#!/bin/bash

# Ensure ir module is findable
export PYTHONPATH=/opt/son_ir:/app:${PYTHONPATH:-}

# Copy the reference optimizer into the application directory
cp /solution/optimizer.py /app/optimizer.py
