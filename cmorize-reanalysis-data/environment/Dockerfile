FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y \
    python3-pip \
    python3-dev \
    python3-numpy \
    python3-netcdf4 \
    netcdf-bin \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY cmor_spec.json /data/cmor_spec.json
COPY errata.txt /data/errata.txt
COPY generate_raw_data.py /tmp/generate_raw_data.py

RUN python3 /tmp/generate_raw_data.py && rm /tmp/generate_raw_data.py

WORKDIR /app
