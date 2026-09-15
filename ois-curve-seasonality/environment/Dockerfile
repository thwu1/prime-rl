FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip sqlite3 make jq && \
    rm -rf /var/lib/apt/lists/*

COPY market_data.json /app/data/market_data.json
COPY holidays.json /app/data/holidays.json
COPY sofr_fixings.csv /app/data/sofr_fixings.csv
COPY portfolio.yaml /app/data/portfolio.yaml

RUN mkdir -p /app/output

WORKDIR /app
