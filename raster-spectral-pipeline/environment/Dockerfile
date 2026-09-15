FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-numpy \
    python3-gdal \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY generate_data.py /tmp/generate_data.py
COPY criteria.json /app/criteria.json

RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.3 rasterio==1.3.10 shapely==2.0.6 numpy==1.26.4
