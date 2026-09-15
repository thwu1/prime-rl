#!/bin/bash

pip3 install pytest==8.3.4 -q 2>/dev/null

source /opt/ros/jazzy/setup.bash

# Kill any orphan ROS processes left over from solve.sh
pkill -9 -f "sensor_publisher|data_processor|anomaly_filter|result_writer" 2>/dev/null || true
ros2 daemon stop 2>/dev/null || true
sleep 3

cd /app/ros2_ws

# Clean and rebuild from source to ensure executables are properly installed
# (--symlink-install is unreliable with Python 3.12 / modern pip for console_scripts)
rm -rf build install log
colcon build 2>&1
BUILD_EXIT=$?

if [ $BUILD_EXIT -ne 0 ]; then
    echo "Build failed with exit code $BUILD_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

source install/setup.bash

# Verify executables exist
for exe in sensor_publisher data_processor anomaly_filter result_writer; do
    if [ ! -f "install/data_pipeline/lib/data_pipeline/$exe" ]; then
        echo "WARNING: executable $exe not found in expected location"
    fi
done

rm -rf /app/output
mkdir -p /app/output

ros2 launch data_pipeline pipeline_launch.py &
LAUNCH_PID=$!

TIMEOUT=90
ELAPSED=0
while [ ! -f /app/output/results.csv ] && [ $ELAPSED -lt $TIMEOUT ]; do
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done

sleep 5

kill $LAUNCH_PID 2>/dev/null || true
wait $LAUNCH_PID 2>/dev/null || true

# Clean up all ROS processes
pkill -9 -f "sensor_publisher|data_processor|anomaly_filter|result_writer" 2>/dev/null || true
ros2 daemon stop 2>/dev/null || true
sleep 2

pytest /tests/test_state.py -v 2>&1
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit 0
