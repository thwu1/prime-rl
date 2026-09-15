
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://github.com/duckdb/duckdb/releases/download/v1.2.0/duckdb_cli-linux-amd64.zip \
    && unzip duckdb_cli-linux-amd64.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/duckdb \
    && rm duckdb_cli-linux-amd64.zip

RUN pip3 install duckdb==1.2.0

RUN mkdir -p /app/data /app/output

COPY generate_data.py /app/generate_data.py

RUN cd /app && python3 generate_data.py

WORKDIR /app
