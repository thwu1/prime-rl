FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY peripheral.yaml /app/peripheral.yaml
COPY transforms.yaml /app/transforms.yaml
COPY ir_reference.md /app/ir_reference.md

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 pyyaml==6.0.2
