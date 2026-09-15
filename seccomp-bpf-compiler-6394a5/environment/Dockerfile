FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        linux-libc-dev \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY policy.txt /app/policy.txt
COPY bpf_compiler.c /app/bpf_compiler.c
COPY Makefile /app/Makefile

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
