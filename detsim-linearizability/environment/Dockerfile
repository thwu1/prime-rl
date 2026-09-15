FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/fault_configs

COPY dessim.py /usr/local/lib/dessim.py
COPY setup_traces.py /tmp/setup_traces.py
COPY dessim.py /tmp/dessim.py
COPY example_config.toml /app/example_config.toml
COPY pipeline_stub.py /app/pipeline.py

RUN printf '#!/bin/sh\npython3 /usr/local/lib/dessim.py "$@"\n' > /usr/local/bin/dessim && \
    chmod +x /usr/local/bin/dessim

RUN python3 /tmp/setup_traces.py /app/traces.db && \
    rm /tmp/setup_traces.py /tmp/dessim.py

WORKDIR /app
