
FROM python:3.12-slim AS builder
RUN pip install numpy==2.1.3
COPY generate_captures.py /tmp/generate_captures.py
RUN python3 /tmp/generate_captures.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    octave \
    xxd \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/captures/ /app/captures/

RUN mkdir -p /app/decoded /app/demod

WORKDIR /app
