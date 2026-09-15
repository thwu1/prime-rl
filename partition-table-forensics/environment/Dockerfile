
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y python3 && rm -rf /var/lib/apt/lists/*
COPY generate_binaries.py /tmp/generate_binaries.py
RUN python3 /tmp/generate_binaries.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 python3-pip xxd binutils file && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/dumps/ /app/dumps/
COPY gen_esp32part.py /app/tools/gen_esp32part.py
COPY reference_formats.txt /app/reference/formats.txt
WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
