FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    make \
    python3-pip \
    valgrind \
    binutils \
    strace \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/include

COPY app/include/config.h /app/include/config.h
COPY app/include/spsc_queue.h /app/include/spsc_queue.h
COPY app/include/shm_protocol.h /app/include/shm_protocol.h
COPY app/stress_test.cpp /app/stress_test.cpp
COPY app/Makefile /app/Makefile

WORKDIR /app
