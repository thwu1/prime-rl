FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    gdb \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/traces /app/golden

# Generate memory access traces
COPY gen_traces.py /tmp/gen_traces.py
RUN python3 /tmp/gen_traces.py && rm /tmp/gen_traces.py

# Install query configuration
COPY queries.json /app/queries.json

# Install C simulation core and build
COPY cache_core.c /app/src/cache_core.c
COPY src_makefile /app/src/Makefile
RUN cd /app/src && make

# Install Python orchestrator
COPY cachesim.py /app/cachesim.py

# Install reference outputs
COPY golden_sim1.json /app/golden/sim1.json
COPY golden_sd_small.json /app/golden/sd_small.json

WORKDIR /app
