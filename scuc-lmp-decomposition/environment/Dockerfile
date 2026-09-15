FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    coinor-cbc \
    glpk-utils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results

COPY data/network.m /app/data/network.m
COPY data/gen_config.json /app/data/gen_config.json
COPY data/load_profile.csv /app/data/load_profile.csv
COPY data/reserve_req.json /app/data/reserve_req.json

WORKDIR /app
