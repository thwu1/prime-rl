
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    glpk-utils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY accel_sim.c /tmp/accel_sim.c
RUN gcc -O2 -o /app/accel_sim /tmp/accel_sim.c && rm /tmp/accel_sim.c

COPY fleet.json /app/fleet.json
COPY dag.json /app/dag.json
COPY topology.json /app/topology.json

WORKDIR /app
