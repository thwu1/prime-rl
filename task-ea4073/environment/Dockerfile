FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    cdo \
    python3-pip \
    python3-netcdf4 \
    python3-numpy \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && \
    cdo -f nc -s setgrid,n16 /app/data/tasmax_daily_raw.nc /app/data/tasmax_daily.nc && \
    rm -f /app/data/tasmax_daily_raw.nc /tmp/generate_data.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
