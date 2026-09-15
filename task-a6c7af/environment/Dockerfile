FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip python3-dev sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/data

COPY data/co2_250K.tsv /app/data/co2_250K.tsv
COPY data/co2_300K.tsv /app/data/co2_300K.tsv
COPY data/co2_350K.tsv /app/data/co2_350K.tsv
COPY data/co2_400K.tsv /app/data/co2_400K.tsv
COPY data/critical_measurements.csv /app/data/critical_measurements.csv
COPY data/co2_saturation_nist.html /app/data/co2_saturation_nist.html

WORKDIR /app
