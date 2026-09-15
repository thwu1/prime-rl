#!/bin/bash

source /opt/ros/jazzy/setup.bash

# Clean up any stale ROS state
ros2 daemon stop 2>/dev/null || true
pkill -9 -f "sensor_publisher|data_processor|anomaly_filter|result_writer" 2>/dev/null || true
sleep 3

# Apply all bug fixes and implement anomaly_filter
python3 /solution/fix_pipeline.py

# Build the workspace (no --symlink-install: Python 3.12 editable installs
# don't reliably create console_scripts in the ament lib directory)
cd /app/ros2_ws
rm -rf build install log
colcon build 2>&1
BUILD_EXIT=$?

if [ $BUILD_EXIT -ne 0 ]; then
    echo "Build failed with exit code $BUILD_EXIT"
    exit 1
fi

# Source workspace overlay
source install/setup.bash

# Run the pipeline to produce output
rm -rf /app/output && mkdir -p /app/output

ros2 launch data_pipeline pipeline_launch.py &
LAUNCH_PID=$!

# Wait for output file (pipeline needs ~20s: lifecycle setup + data collection)
TIMEOUT=120
ELAPSED=0
while [ ! -f /app/output/results.csv ] && [ $ELAPSED -lt $TIMEOUT ]; do
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done

# Give extra time for file to be fully written
sleep 5

# Clean shutdown
kill $LAUNCH_PID 2>/dev/null || true
wait $LAUNCH_PID 2>/dev/null || true

# Kill any remaining ROS processes
pkill -9 -f "sensor_publisher|data_processor|anomaly_filter|result_writer" 2>/dev/null || true
ros2 daemon stop 2>/dev/null || true
sleep 2

echo "Pipeline completed. Output at /app/output/results.csv"
if [ -f /app/output/results.csv ]; then
    cat /app/output/results.csv
else
    echo "WARNING: results.csv was not produced"
fi

exit 0
