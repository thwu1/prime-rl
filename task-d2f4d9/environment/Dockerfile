FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make strace xxd && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY gen_filters.py /tmp/gen_filters.py
COPY policies.json /app/policies.json
COPY bpf_spec.md /app/bpf_spec.md
COPY seccomp_loader.c /app/seccomp_loader.c
COPY Makefile /app/Makefile

RUN python3 /tmp/gen_filters.py && rm /tmp/gen_filters.py

WORKDIR /app
