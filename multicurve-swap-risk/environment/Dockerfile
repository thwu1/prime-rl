FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install QuantLib==1.35

RUN mkdir -p /app

COPY market_data.json /app/market_data.json
COPY portfolio.json /app/portfolio.json

WORKDIR /app
