
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y gdal-bin python3-gdal python3-pip python3-numpy && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data/landsat /app/output

COPY generate_data.py /tmp/generate_data.py

RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

RUN ls -la /data/landsat/ && python3 -c "import json; json.load(open('/data/landsat/parameters.json')); print('Data verification OK')"

WORKDIR /app
