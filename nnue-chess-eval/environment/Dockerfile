FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
COPY nnue_oracle.c /tmp/nnue_oracle.c
RUN gcc -O2 -s -o /tmp/nnue_oracle /tmp/nnue_oracle.c

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY --from=builder /tmp/nnue_oracle /app/nnue_oracle
RUN chmod +x /app/nnue_oracle

COPY generate_network.py /tmp/generate_network.py
RUN python3 /tmp/generate_network.py && rm /tmp/generate_network.py

COPY spec.md /app/spec.md
COPY nnue_stub.py /app/nnue.py

WORKDIR /app
