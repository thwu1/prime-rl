FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install ClickHouse and dependencies
RUN apt-get update && \
    apt-get install -y apt-transport-https ca-certificates curl gnupg python3-pip && \
    curl -fsSL 'https://packages.clickhouse.com/rpm/lts/repodata/repomd.xml.key' | \
        gpg --dearmor -o /usr/share/keyrings/clickhouse-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/clickhouse-keyring.gpg] https://packages.clickhouse.com/deb stable main" > \
        /etc/apt/sources.list.d/clickhouse.list && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y clickhouse-server clickhouse-client && \
    rm -rf /var/lib/apt/lists/*

# Generate synthetic log data and load into ClickHouse (single layer to avoid bloat)
COPY generate_logs.py /app/generate_logs.py
COPY setup_clickhouse.sh /app/setup_clickhouse.sh
RUN python3 /app/generate_logs.py && \
    chmod +x /app/setup_clickhouse.sh && /app/setup_clickhouse.sh && \
    rm -f /app/data/raw_logs.tsv

WORKDIR /app
