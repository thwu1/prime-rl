
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    cc65 \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY buggy_emulator.py /app/emulator.py
COPY manifest.json /app/manifest.json
COPY expected.json /app/expected.json
COPY gen_binary.py /tmp/gen_binary.py

RUN python3 /tmp/gen_binary.py && rm /tmp/gen_binary.py

WORKDIR /app
