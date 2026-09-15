FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/orders /app/data/inventory /app/data/config /app/docs /app/output

COPY data/orders/regular_orders.csv /app/data/orders/regular_orders.csv
COPY data/orders/priority_orders.csv /app/data/orders/priority_orders.csv
COPY data/config/cutting_params.json /app/data/config/cutting_params.json
COPY docs/cutting_operations.txt /app/docs/cutting_operations.txt
COPY data/inventory/create_db.py /tmp/create_db.py

RUN python3 /tmp/create_db.py && rm /tmp/create_db.py

WORKDIR /app
