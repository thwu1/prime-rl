FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Copy planner source to a stable backup location that survives any /app mount
RUN mkdir -p /opt/planner_src
COPY app/planner/ /opt/planner_src/planner/

# Also install into /app for direct agent access
RUN mkdir -p /app/planner && cp -r /opt/planner_src/planner/* /app/planner/

WORKDIR /app
