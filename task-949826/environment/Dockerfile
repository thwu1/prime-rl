FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    binutils-riscv64-linux-gnu \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/binaries

COPY gen_task_data.py /tmp/gen_task_data.py
RUN python3 /tmp/gen_task_data.py && rm /tmp/gen_task_data.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
