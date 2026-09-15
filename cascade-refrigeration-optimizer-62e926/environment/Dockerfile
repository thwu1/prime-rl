FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/site /app/data/equipment/compressors
COPY data/systems.json /app/data/systems.json
COPY data/refrigerant_inventory.csv /app/data/refrigerant_inventory.csv
COPY data/site/conditions.json /app/data/site/conditions.json
COPY data/site/ambient_profile.csv /app/data/site/ambient_profile.csv
COPY data/site/environmental.json /app/data/site/environmental.json
COPY data/equipment/compressors/COMP-LTC-A.json /app/data/equipment/compressors/COMP-LTC-A.json
COPY data/equipment/compressors/COMP-LTC-B.json /app/data/equipment/compressors/COMP-LTC-B.json
COPY data/equipment/compressors/COMP-LTC-C.json /app/data/equipment/compressors/COMP-LTC-C.json
COPY data/equipment/compressors/COMP-HTC-A.json /app/data/equipment/compressors/COMP-HTC-A.json
COPY data/equipment/compressors/COMP-HTC-B.json /app/data/equipment/compressors/COMP-HTC-B.json
COPY data/equipment/compressors/COMP-HTC-C.json /app/data/equipment/compressors/COMP-HTC-C.json

WORKDIR /app
