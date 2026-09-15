FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    build-essential \
    clang \
    python3 \
    python3-pip \
    valgrind \
    && rm -rf /var/lib/apt/lists/*

COPY edge_detect.c /app/edge_detect.c
COPY edge_detect_ref.c /app/edge_detect_ref.c
COPY Makefile /app/Makefile
COPY generate_input.py /app/generate_input.py

WORKDIR /app
RUN python3 generate_input.py
