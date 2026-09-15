FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip geotiff-bin libtiff-tools && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/corrupted /app/fixed

COPY manifest.txt /app/manifest.txt
COPY generate_corrupted.py /tmp/generate_corrupted.py
RUN python3 /tmp/generate_corrupted.py && rm /tmp/generate_corrupted.py

WORKDIR /app
