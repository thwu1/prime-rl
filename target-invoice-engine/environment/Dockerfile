FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 make && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pricing_schedule.txt /app/pricing_schedule.txt
COPY schema.sql /app/schema.sql
COPY data/ /app/data/
COPY reference_invoices.json /app/reference_invoices.json

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
