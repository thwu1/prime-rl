
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip xxd bsdextrautils && \
    rm -rf /var/lib/apt/lists/*

COPY setup_task.py /tmp/setup_task.py
COPY gguf_v3_spec.md /tmp/gguf_v3_spec.md
RUN python3 /tmp/setup_task.py && \
    cp /tmp/gguf_v3_spec.md /app/gguf_spec.md && \
    rm /tmp/setup_task.py /tmp/gguf_v3_spec.md
