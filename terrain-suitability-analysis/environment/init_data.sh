#!/bin/bash
# Copy task data from build-time location to /app/ working directory
# This is needed because /app/ may be a VOLUME that doesn't persist build-time files
if [ -d /opt/task_data ] && [ ! -f /app/dem.tif ]; then
    mkdir -p /app/output
    cp /opt/task_data/* /app/ 2>/dev/null || true
fi
