FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    libnetcdf-dev \
    libhdf5-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/config /app/data /app/output

COPY config/ /app/config/

WORKDIR /app
