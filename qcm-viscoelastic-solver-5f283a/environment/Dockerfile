FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/config /app/data/water_cal /app/data/rigid_film /app/data/polymer_coating

COPY config/crystal.toml /app/config/crystal.toml
COPY data/water_cal/metadata.json /app/data/water_cal/metadata.json
COPY data/water_cal/measurements.csv /app/data/water_cal/measurements.csv
COPY data/rigid_film/metadata.json /app/data/rigid_film/metadata.json
COPY data/rigid_film/measurements.csv /app/data/rigid_film/measurements.csv
COPY data/polymer_coating/metadata.json /app/data/polymer_coating/metadata.json
COPY data/polymer_coating/measurements.csv /app/data/polymer_coating/measurements.csv

