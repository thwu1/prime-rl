FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY encoder.py /app/encoder.py
COPY spec.md /app/spec.md
COPY setup_frames.py /tmp/setup_frames.py
RUN python3 /tmp/setup_frames.py && rm /tmp/setup_frames.py

WORKDIR /app
