FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /tmp/build
COPY asset_returns.csv /tmp/build/asset_returns.csv
COPY generate_data.py /tmp/build/generate_data.py
RUN python3 /tmp/build/generate_data.py && rm -rf /tmp/build

COPY config.toml /app/config.toml

WORKDIR /app
