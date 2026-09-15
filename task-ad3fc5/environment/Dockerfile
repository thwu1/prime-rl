FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    make \
    valgrind \
    python3-pip \
    libasan8 \
    libubsan1 \
    && rm -rf /var/lib/apt/lists/*

RUN rm -rf /app && mkdir -p /app/traces
COPY app/Makefile /app/Makefile
COPY app/hsm.h /app/hsm.h
COPY app/hsm.c /app/hsm.c
COPY app/main.c /app/main.c
COPY app/test_sm.h /app/test_sm.h
COPY app/test_sm.c /app/test_sm.c
COPY app/spec.md /app/spec.md
COPY app/traces/input.txt /app/traces/input.txt
COPY app/traces/expected.txt /app/traces/expected.txt
WORKDIR /app
