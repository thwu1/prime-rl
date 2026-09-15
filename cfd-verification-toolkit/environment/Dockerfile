FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gmsh \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY ci2_init_legacy.py /app/data/ci2_init_legacy.py
COPY convergence_data.csv /app/data/convergence_data.csv
COPY channel.geo /app/data/channel.geo

WORKDIR /app
