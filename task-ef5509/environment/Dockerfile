
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y gcc g++ make python3-pip clang libomp-dev && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/build

COPY src/ /app/src/
COPY Makefile /app/Makefile

WORKDIR /app
