FROM python:3.12-slim AS builder
COPY generate_logs.py /tmp/generate_logs.py
RUN mkdir -p /app/flights && python3 /tmp/generate_logs.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/flights/ /app/flights/
COPY param_ranges.json /app/param_ranges.json
COPY safety_spec.json /app/safety_spec.json
COPY format_hint.txt /app/format_hint.txt

WORKDIR /app
