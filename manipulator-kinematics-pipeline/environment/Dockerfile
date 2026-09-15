FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY robot.urdf /app/robot.urdf
COPY waypoints.json /app/waypoints.json
COPY config.json /app/config.json
COPY robot_spec.json /app/robot_spec.json
