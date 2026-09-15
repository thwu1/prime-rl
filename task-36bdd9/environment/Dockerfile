FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/CMU-SAFARI/ramulator2 /app/ramulator2

RUN mkdir -p /app/sim_output /app/traces /app/configs

WORKDIR /app
