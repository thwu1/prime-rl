FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/knuth /app/problems /app/results

COPY dlx1.w /app/knuth/dlx1.w
COPY gb_flip.h /app/knuth/gb_flip.h
COPY setup.py /tmp/setup.py
RUN python3 /tmp/setup.py && rm /tmp/setup.py

WORKDIR /app
