FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-dev gcc make && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY spec.md /app/spec.md
COPY flip_reference.js /app/flip_reference.js
COPY flip_sim.py /app/flip_sim.py

WORKDIR /app
