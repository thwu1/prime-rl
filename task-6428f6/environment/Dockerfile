FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip gdal-bin sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output /app/config /app/data/forcing

COPY data/catchments.geojson /tmp/catchments.geojson
COPY data/nexuses.geojson /tmp/nexuses.geojson
COPY data/cfe_bmi_config.txt /app/config/cfe_bmi_config.txt
COPY data/pet_bmi_config.txt /app/config/pet_bmi_config.txt
COPY scripts/generate_forcing.py /tmp/generate_forcing.py

RUN ogr2ogr -f GPKG /app/data/hydrofabric.gpkg /tmp/catchments.geojson -nln catchments && \
    ogr2ogr -f GPKG /app/data/hydrofabric.gpkg /tmp/nexuses.geojson -nln nexuses -append

RUN python3 /tmp/generate_forcing.py

RUN rm -f /tmp/catchments.geojson /tmp/nexuses.geojson /tmp/generate_forcing.py

WORKDIR /app
