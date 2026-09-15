FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    gdal-bin \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 rasterio==1.3.10 pyproj==3.6.1 shapely==2.0.6 fiona==1.9.6 geopandas==0.14.4

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && \
    test -f /app/data/imagery.tif && \
    test -f /app/data/zones.geojson && \
    test -f /app/data/samples.csv && \
    test -f /app/data/metadata.json && \
    rm /tmp/generate_data.py

WORKDIR /app
