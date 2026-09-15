FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    nco \
    python3-pip \
    python3-numpy \
    python3-netcdf4 \
    && rm -rf /var/lib/apt/lists/*

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

RUN mkdir -p /app/output /app/work
WORKDIR /app
