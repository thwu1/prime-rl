FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    python3 \
    python3-pip \
    binutils \
    gdb \
    strace \
    ltrace \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pktool_ref.c /tmp/pktool_ref.c
RUN gcc -O2 -o /app/pktool-ref /tmp/pktool_ref.c && \
    strip -s /app/pktool-ref && \
    rm /tmp/pktool_ref.c && \
    chmod +x /app/pktool-ref

COPY gen_samples.py /tmp/gen_samples.py
RUN python3 /tmp/gen_samples.py && rm /tmp/gen_samples.py

COPY protocol_spec.md /app/protocol_spec.md
