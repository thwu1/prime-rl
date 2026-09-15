FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install NCO suite and netCDF utilities for the task environment.
RUN apt-get update && apt-get install -y \
    nco \
    netcdf-bin \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install numpy and netCDF4 via pip for seed data generation.
RUN pip3 install numpy==2.1.3 netCDF4==1.7.2 -q

RUN mkdir -p /app/data /app/output

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
