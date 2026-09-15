
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/fhir_data

COPY generate_data.py /tmp/generate_data.py
COPY generate_warehouse.py /tmp/generate_warehouse.py
RUN python3 /tmp/generate_data.py && python3 /tmp/generate_warehouse.py && rm -f /tmp/generate_data.py /tmp/generate_warehouse.py

WORKDIR /app
