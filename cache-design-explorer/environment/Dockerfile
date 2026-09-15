FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y gcc make gdb valgrind python3-pip && rm -rf /var/lib/apt/lists/*

COPY cache.h /app/cache.h
COPY cache.c /app/cache.c
COPY cachesim.c /app/cachesim.c
COPY Makefile_app /app/Makefile
COPY spec.md /app/spec.md
COPY trace_ref.txt /app/traces/trace_ref.txt
COPY gen_traces.py /tmp/gen_traces.py

RUN python3 /tmp/gen_traces.py && rm /tmp/gen_traces.py
RUN cd /app && make

WORKDIR /app
