FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip gdal-bin python3-gdal jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/rasters /app/stac_items /app/schema /app/output

COPY create_data.py /tmp/create_data.py
COPY create_stac.py /tmp/create_stac.py

RUN python3 /tmp/create_data.py && \
    python3 /tmp/create_stac.py && \
    rm /tmp/create_data.py /tmp/create_stac.py

COPY schema/report_schema.json /app/schema/report_schema.json

WORKDIR /app
