
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install DuckDB CLI
RUN wget -q https://github.com/duckdb/duckdb/releases/download/v1.1.3/duckdb_cli-linux-amd64.zip \
    && unzip duckdb_cli-linux-amd64.zip -d /usr/local/bin/ \
    && rm duckdb_cli-linux-amd64.zip \
    && chmod +x /usr/local/bin/duckdb

# Install DuckDB Python package (matches CLI version)
RUN pip3 install duckdb==1.1.3

# Pre-install TPC-H extension for data generation
RUN python3 -c "import duckdb; con = duckdb.connect(); con.execute('INSTALL tpch'); con.close()"

# Generate warehouse data and source system exports
COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

WORKDIR /app
