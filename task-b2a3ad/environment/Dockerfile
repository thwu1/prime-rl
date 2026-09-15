FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    make \
    gdb \
    valgrind \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY fdtd3d.h /app/fdtd3d.h
COPY main.c /app/main.c
COPY reference.c /app/reference.c
COPY solver.c /app/solver.c
COPY analyze.c /app/analyze.c
COPY Makefile /app/Makefile

WORKDIR /app
