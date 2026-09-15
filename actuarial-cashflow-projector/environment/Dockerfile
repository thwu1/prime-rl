FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output /app/reference

COPY data/model_points.csv /app/data/model_points.csv
COPY data/product_spec.csv /app/data/product_spec.csv
COPY data/mort_table.csv /app/data/mort_table.csv
COPY data/disc_rate_ann.csv /app/data/disc_rate_ann.csv
COPY data/surr_charge_table.csv /app/data/surr_charge_table.csv
COPY data/inv_return.csv /app/data/inv_return.csv

COPY reference/CashValue_ME_Projection.py /app/reference/CashValue_ME_Projection.py

WORKDIR /app
