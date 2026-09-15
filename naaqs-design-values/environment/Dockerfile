FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY annual_summary_2021_2023.csv /app/data/annual_summary_2021_2023.csv

WORKDIR /app
