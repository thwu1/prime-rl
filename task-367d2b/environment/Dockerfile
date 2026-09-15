
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-gdal gdal-bin \
    spatialite-bin sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY setup_catalog.py /tmp/setup_catalog.py
COPY pipeline.log /app/pipeline.log
COPY missions.json /app/missions.json

RUN python3 /tmp/setup_catalog.py && rm /tmp/setup_catalog.py

WORKDIR /app
