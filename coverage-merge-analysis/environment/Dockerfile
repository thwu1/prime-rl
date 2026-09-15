
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY app/setup_coverage_dbs.py /tmp/setup_coverage_dbs.py
COPY app/vplan.yaml /data/vplan.yaml
COPY app/output_schema.json /data/output_schema.json

RUN python3 /tmp/setup_coverage_dbs.py && rm /tmp/setup_coverage_dbs.py

RUN mkdir -p /app
WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
