FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    llvm-18 \
    binutils \
    xxd \
    bsdextrautils \
    && rm -rf /var/lib/apt/lists/*

COPY spec.md /app/spec.md
COPY gen_programs.py /tmp/gen_programs.py
RUN python3 /tmp/gen_programs.py && rm /tmp/gen_programs.py

WORKDIR /app
