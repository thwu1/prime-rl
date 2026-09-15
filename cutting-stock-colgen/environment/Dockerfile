
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/materials /app/orders/archive /app/production /app/output

COPY README.txt /app/README.txt
COPY stock_specs.toml /app/materials/stock_specs.toml
COPY scrap_rates.csv /app/materials/scrap_rates.csv
COPY batch_q1.csv /app/orders/batch_q1.csv
COPY batch_q2.csv /app/orders/batch_q2.csv
COPY batch_q3.csv /app/orders/batch_q3.csv
COPY canceled.csv /app/orders/canceled.csv
COPY 2023_orders.csv /app/orders/archive/2023_orders.csv
COPY prior_run.log /app/production/prior_run.log
COPY machine_config.ini /app/production/machine_config.ini

WORKDIR /app
