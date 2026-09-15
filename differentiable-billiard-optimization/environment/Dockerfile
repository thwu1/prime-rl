FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/cdual

COPY problem.json /app/problem.json
COPY cdual/dual.c /app/cdual/dual.c
COPY cdual/dual.h /app/cdual/dual.h
COPY cdual/Makefile /app/cdual/Makefile
COPY dual_c.py /app/dual_c.py
COPY dual.py /app/dual.py
COPY physics.py /app/physics.py
COPY optimize.py /app/optimize.py

WORKDIR /app
