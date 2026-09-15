FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y gcc clang make python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY safe_math.h /app/safe_math.h
COPY crc32.h /app/crc32.h
COPY expr_gen.c /app/expr_gen.c
COPY harness.sh /app/harness.sh
COPY Makefile /app/Makefile

RUN chmod +x /app/harness.sh

WORKDIR /app
