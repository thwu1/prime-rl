FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    jq \
    sqlite3 \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install DuckDB CLI (analytical SQL database with Parquet/SQLite support)
RUN wget -qO /tmp/duckdb.zip https://github.com/duckdb/duckdb/releases/download/v1.1.3/duckdb_cli-linux-amd64.zip \
    && unzip -o /tmp/duckdb.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/duckdb \
    && rm /tmp/duckdb.zip \
    && duckdb -c "INSTALL sqlite_scanner;"

# Set up hub structure
RUN mkdir -p /app/hub-config /app/data/forecasts /app/output

# Copy hub config and locations
COPY hub-config/tasks.json /app/hub-config/tasks.json
COPY data/locations.csv /app/data/locations.csv

# Copy raw source data to temp for format conversion
COPY data/target.csv /tmp/target.csv
COPY data/forecasts/TeamA-EpiModel.csv /tmp/forecasts/TeamA-EpiModel.csv
COPY data/forecasts/TeamB-Baseline.csv /tmp/forecasts/TeamB-Baseline.csv
COPY data/forecasts/TeamC-Overpredict.csv /tmp/forecasts/TeamC-Overpredict.csv
COPY data/forecasts/TeamD-NarrowCI.csv /tmp/forecasts/TeamD-NarrowCI.csv
COPY data/forecasts/TeamE-Hybrid.csv /tmp/forecasts/TeamE-Hybrid.csv
COPY data/forecasts/TeamF-Corrupt.csv /tmp/forecasts/TeamF-Corrupt.csv

# Run data setup: converts some forecasts to Parquet/NDJSON, target data to SQLite
COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py \
    && rm -f /tmp/setup_data.py /tmp/target.csv \
    && rm -rf /tmp/forecasts

WORKDIR /app
