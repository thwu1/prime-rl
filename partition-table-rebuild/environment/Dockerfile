FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    xxd \
    file \
    && rm -rf /var/lib/apt/lists/*

COPY gen_esp32part.py /tmp/gen_esp32part_clean.py
COPY setup_task.py /tmp/setup_task.py
RUN python3 /tmp/setup_task.py && rm /tmp/setup_task.py /tmp/gen_esp32part_clean.py

WORKDIR /app
