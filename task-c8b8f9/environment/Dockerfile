
FROM python:3.12-slim AS builder
COPY generate_capture.py /tmp/generate_capture.py
RUN python3 /tmp/generate_capture.py /tmp/capture.bin

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    xxd \
    binutils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/firmware/src

COPY --from=builder /tmp/capture.bin /app/capture.bin
COPY firmware/Cargo.toml /app/firmware/Cargo.toml
COPY firmware/src/main.rs /app/firmware/src/main.rs
COPY firmware/src/types.rs /app/firmware/src/types.rs
COPY firmware/src/serial.rs /app/firmware/src/serial.rs

WORKDIR /app
