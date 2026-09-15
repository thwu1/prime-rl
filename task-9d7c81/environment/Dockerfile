FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/tests

COPY algorithms.py /app/src/algorithms.py
COPY test_algorithms.py /app/tests/test_algorithms.py
COPY SPEC.md /app/SPEC.md

WORKDIR /app
