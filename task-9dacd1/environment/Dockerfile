FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    python3-numpy \
    python3-netcdf4 \
    netcdf-bin \
    libnetcdf-dev \
    libhdf5-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Copy data generation script and config files
COPY generate_raw_data.py /tmp/generate_raw_data.py
COPY cmor_table.json /app/cmor_table.json
COPY cmor_config.yml /app/cmor_config.yml

# Generate synthetic raw observational data
RUN python3 /tmp/generate_raw_data.py && rm /tmp/generate_raw_data.py

# Create output directory
RUN mkdir -p /app/output

WORKDIR /app
