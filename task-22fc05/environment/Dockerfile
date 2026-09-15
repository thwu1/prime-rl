FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 && \
    rm -rf /var/lib/apt/lists/*

COPY setup_data.py /tmp/setup_data.py
COPY vindex_hash_reference.go /tmp/vindex_hash_reference.go

RUN python3 /tmp/setup_data.py && \
    mkdir -p /app/reference && \
    cp /tmp/vindex_hash_reference.go /app/reference/vindex_hash.go && \
    rm -f /tmp/setup_data.py /tmp/vindex_hash_reference.go

WORKDIR /app
