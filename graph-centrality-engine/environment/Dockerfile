FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY app/graph.h      /app/graph.h
COPY app/graph.c      /app/graph.c
COPY app/main.c       /app/main.c
COPY app/Makefile     /app/Makefile
COPY app/generate_graphs.py /app/generate_graphs.py

RUN python3 /app/generate_graphs.py && rm /app/generate_graphs.py

WORKDIR /app
