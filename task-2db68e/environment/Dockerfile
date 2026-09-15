FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY data/CPIAUCSL.csv /app/data/CPIAUCSL.csv
COPY data/GDP.csv /app/data/GDP.csv
COPY data/FEDFUNDS.csv /app/data/FEDFUNDS.csv
COPY data/UNRATE.csv /app/data/UNRATE.csv
COPY data/M2SL.csv /app/data/M2SL.csv
COPY data/DGS10.csv /app/data/DGS10.csv
COPY data/T10Y2Y.csv /app/data/T10Y2Y.csv
COPY data/PAYEMS.csv /app/data/PAYEMS.csv

WORKDIR /app
