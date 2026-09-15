FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    make \
    valgrind \
    python3-pip \
    time \
    && rm -rf /var/lib/apt/lists/*

COPY pipeline.cpp /app/pipeline.cpp
COPY Makefile /app/Makefile

WORKDIR /app
