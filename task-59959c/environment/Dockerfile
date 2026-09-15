FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 xarray==2024.9.0 zarr==2.18.3 numcodecs==0.12.1 \
    dask==2024.8.0 pandas==2.2.3 fsspec==2024.9.0 -q

RUN mkdir -p /app

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
