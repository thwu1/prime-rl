
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    gnupg \
    apt-transport-https \
    ca-certificates \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL 'https://packages.clickhouse.com/rpm/lts/repodata/repomd.xml.key' | gpg --dearmor -o /usr/share/keyrings/clickhouse-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/clickhouse-keyring.gpg] https://packages.clickhouse.com/deb stable main" > /etc/apt/sources.list.d/clickhouse.list \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y clickhouse-server clickhouse-client \
    && rm -rf /var/lib/apt/lists/*

COPY clickhouse_docker.xml /etc/clickhouse-server/config.d/docker.xml

# Change ownership of all ClickHouse directories to root so the server
# can run as root without the MISMATCHING_USERS_FOR_PROCESS_AND_DATA error
# that ClickHouse 26.x enforces.
RUN mkdir -p /var/lib/clickhouse /var/log/clickhouse-server /var/run/clickhouse-server \
    && chown -R root:root /var/lib/clickhouse /var/log/clickhouse-server /var/run/clickhouse-server

RUN mkdir -p /app/data /app/results

COPY generate_data.py /app/generate_data.py
RUN python3 /app/generate_data.py

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /app

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sleep", "infinity"]
