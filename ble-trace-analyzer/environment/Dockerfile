
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tshark \
    openssl \
    xxd \
    && rm -rf /var/lib/apt/lists/*

COPY gen_traces.py /tmp/gen_traces.py
RUN python3 /tmp/gen_traces.py && rm /tmp/gen_traces.py

COPY format_spec.txt /app/format_spec.txt
COPY ble_encryption_spec.md /app/ble_encryption_spec.md

RUN mkdir -p /app/results

WORKDIR /app
