FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y gcc python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY engine.c /tmp/engine.c
RUN gcc -shared -fPIC -O2 -o /app/libfairkalah.so /tmp/engine.c && strip /app/libfairkalah.so
RUN gcc -O2 -DCLI_BUILD -o /tmp/fairkalah_cli /tmp/engine.c
COPY gen_traces.py /tmp/gen_traces.py
RUN python3 /tmp/gen_traces.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc binutils gdb strace ltrace sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/libfairkalah.so /app/libfairkalah.so
COPY --from=builder /app/traces /app/traces
COPY positions.json /app/positions.json
