FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    cmake \
    && rm -rf /var/lib/apt/lists/*

COPY problem.yaml /app/problem.yaml

RUN mkdir -p /app/results

WORKDIR /app
