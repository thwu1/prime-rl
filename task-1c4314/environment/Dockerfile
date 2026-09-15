FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    openssl \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/certs /setup

COPY derp_spec.md /app/derp_spec.md
COPY envelope_spec.md /app/envelope_spec.md
COPY schema.sql /app/schema.sql
COPY generate_capture.py /setup/generate_capture.py

RUN python3 /setup/generate_capture.py && rm -rf /setup

WORKDIR /app
