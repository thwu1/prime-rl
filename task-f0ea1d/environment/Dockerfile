FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY nec2_types.h nec2_parser.h nec2_parser.c /app/
COPY deck_parser.h deck_parser.c /app/
COPY antenna_metrics.h antenna_metrics.c /app/
COPY nec2_char.c Makefile /app/
COPY data/ /app/data/

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
