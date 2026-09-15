FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip curl unzip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install duckdb==1.2.0

RUN curl -fsSL https://github.com/duckdb/duckdb/releases/download/v1.2.0/duckdb_cli-linux-amd64.zip -o /tmp/duckdb.zip && \
    cd /tmp && unzip duckdb.zip && mv duckdb /usr/local/bin/duckdb && chmod +x /usr/local/bin/duckdb && \
    rm /tmp/duckdb.zip

RUN mkdir -p /app/output

COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

WORKDIR /app
