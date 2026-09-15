
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-yaml gcc && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/output /app/configs /app/tools /app/traces

COPY configs /app/configs
COPY traces /app/traces
COPY tools/trace_reader.c /app/tools/trace_reader.c
COPY simulator.py /app/simulator.py

RUN gcc -o /app/tools/trace_reader /app/tools/trace_reader.c -lm

WORKDIR /app
