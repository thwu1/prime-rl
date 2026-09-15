
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

RUN apt-get update && apt-get install -y \
    python3 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY generate_firmware.py /tmp/generate_firmware.py
RUN mkdir -p /app && python3 /tmp/generate_firmware.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    binwalk \
    radare2 \
    binutils \
    file \
    xxd \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/firmware.bin /app/firmware.bin
WORKDIR /app
