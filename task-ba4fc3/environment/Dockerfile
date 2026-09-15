
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip graphviz sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/examples

COPY pool_spec.md /app/POOL_SPEC.md
COPY example_pool.json /app/examples/example_pool.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
