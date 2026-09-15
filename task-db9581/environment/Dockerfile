FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip xxd bsdextrautils file && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/results

COPY generate_flash.py /tmp/generate_flash.py
COPY flash_spec.md /app/flash_spec.md

RUN python3 /tmp/generate_flash.py && rm /tmp/generate_flash.py

WORKDIR /app
