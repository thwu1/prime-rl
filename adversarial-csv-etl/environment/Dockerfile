FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install DuckDB for data generation
RUN pip3 install duckdb==1.1.0

# Generate the financial database
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

RUN mkdir -p /app/output
WORKDIR /app

