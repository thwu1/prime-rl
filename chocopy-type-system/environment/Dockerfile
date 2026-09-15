
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip binutils-riscv64-linux-gnu && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY compiler_output.s /tmp/compiler_output.s
RUN riscv64-linux-gnu-as -o /app/compiler_output.o /tmp/compiler_output.s && \
    rm /tmp/compiler_output.s

COPY class_defs.py /app/class_defs.py
COPY chocopy_types_skeleton.py /app/chocopy_types.py
COPY spec.md /app/spec.md
