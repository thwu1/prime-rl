FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    clang \
    python3-pip \
    make \
    && rm -rf /var/lib/apt/lists/*

COPY setup/harness.h /app/harness.h
COPY setup/new_tests.txt /app/new_tests.txt
COPY setup/tests/ /app/tests/

WORKDIR /app
