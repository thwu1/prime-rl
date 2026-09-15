FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gdal-bin \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir numpy==1.26.4 rasterio==1.3.10

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY broken_pipeline.py /app/pipeline.py
RUN cd /app && python3 pipeline.py

COPY validation_report.txt /app/validation_report.txt

WORKDIR /app
