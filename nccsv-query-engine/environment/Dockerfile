FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    netcdf-bin \
    libnetcdf-dev \
    libhdf5-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /app/data /app/output

COPY ocean_profiles.nccsv /app/data/ocean_profiles.nccsv
