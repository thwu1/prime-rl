FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /app/docs /app/results

COPY config.toml /app/config.toml
COPY benchmark_specs.md /app/docs/benchmark_specs.md
COPY benchmark_spec.toml /app/docs/benchmark_spec.toml
COPY standard_configs.toml /app/docs/standard_configs.toml
COPY evaluation_protocol.md /app/docs/evaluation_protocol.md

COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
