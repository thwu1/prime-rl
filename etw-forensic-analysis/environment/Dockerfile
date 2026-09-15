FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    xxd \
    binutils \
    radare2 \
    yara \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY dump_format.md /app/dump_format.md
COPY reference_flags.txt /app/reference_flags.txt
COPY attack_vectors.md /app/attack_vectors.md

COPY generate_dump.py /tmp/generate_dump.py
RUN python3 /tmp/generate_dump.py && rm /tmp/generate_dump.py
RUN test -f /app/etw_dump.bin && test -f /app/etw_clean.bin

WORKDIR /app
