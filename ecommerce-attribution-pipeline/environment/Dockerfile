
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install duckdb==1.1.3

RUN mkdir -p /app/output

COPY data_gen.py /tmp/data_gen.py
COPY verify_db.sh /tmp/verify_db.sh
RUN python3 /tmp/data_gen.py && rm -f /app/ecommerce.duckdb.wal /app/ecommerce.duckdb.tmp && chmod +x /tmp/verify_db.sh && /tmp/verify_db.sh && rm /tmp/data_gen.py /tmp/verify_db.sh

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q duckdb==1.1.3 pytest==8.3.4 pandas==2.2.3 numpy==2.1.3
