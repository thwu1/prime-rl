FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip protobuf-compiler && \
    rm -rf /var/lib/apt/lists/*

# Proto schema for the task (correct version used during build only)
COPY proto/ /app/proto/

# Generate protobuf Python bindings for the build-time generator
RUN protoc --python_out=/app/proto/ --proto_path=/app/proto/ /app/proto/game.proto

# Install protobuf library for generator (also useful for agent)
RUN pip3 install protobuf==5.29.3

# Generate replay data using the correct schema
COPY generator.py /tmp/generator.py
RUN python3 /tmp/generator.py

# Tournament configuration
COPY tournament.json /app/tournament.json

# Replace proto with recovered/corrupted version and clean up build artifacts.
# Agent must diagnose and fix any schema issues before parsing replays.
COPY proto_task/game.proto /app/proto/game.proto
RUN rm -f /tmp/generator.py /app/proto/game_pb2.py && rm -rf /app/proto/__pycache__

WORKDIR /app
