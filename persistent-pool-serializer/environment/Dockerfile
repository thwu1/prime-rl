FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

COPY persistent_vector.py /app/persistent_vector.py
COPY snapstore.py /app/snapstore.py
COPY pool_serializer.py /app/pool_serializer.py
COPY schema.sql /app/schema.sql
COPY compact.sh /app/compact.sh
COPY export.sh /app/export.sh

RUN chmod +x /app/compact.sh /app/export.sh

WORKDIR /app
