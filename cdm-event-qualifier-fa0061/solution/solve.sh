#!/bin/bash

# Download Gson for JSON parsing
mkdir -p /app/lib
wget -q "https://repo1.maven.org/maven2/com/google/code/gson/gson/2.11.0/gson-2.11.0.jar" -O /app/lib/gson-2.11.0.jar

# Copy solution implementation
cp /solution/EventQualifier.java /app/src/cdm/EventQualifier.java

# Compile
mkdir -p /app/build
javac -cp "/app/lib/*" -d /app/build /app/src/cdm/EventQualifier.java

# Run the classifier against all event files to verify it works
echo "=== Running classifier on all event files ==="
for event_file in /app/events/evt_*.json; do
    fname=$(basename "$event_file")
    result=$(java -cp "/app/build:/app/lib/*" cdm.EventQualifier "$event_file" 2>/dev/null)
    echo "$fname -> $result"
done
echo "=== Done ==="
