FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip xsltproc sqlite3 make && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY data/nominal_yields.xml /app/data/nominal_yields.xml
COPY data/real_yields.xml /app/data/real_yields.xml
COPY data/h15_rates.csv /app/data/h15_rates.csv
COPY data/tips_securities.json /app/data/tips_securities.json
COPY data/cpi_u_nsa.csv /app/data/cpi_u_nsa.csv

WORKDIR /app
