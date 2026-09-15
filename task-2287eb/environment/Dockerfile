
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y binutils-arm-none-eabi python3-pip && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app
COPY firmware.b64 /tmp/firmware.b64
RUN base64 -d /tmp/firmware.b64 > /app/firmware.elf && rm /tmp/firmware.b64
COPY spec.md /app/spec.md
