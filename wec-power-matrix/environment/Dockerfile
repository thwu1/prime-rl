FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    hdf5-tools \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY data/rm3_hydro_coeffs.csv /app/data/rm3_hydro_coeffs.csv
COPY data/rm3_params.json /app/data/rm3_params.json
COPY data/sea_states.csv /app/data/sea_states.csv

WORKDIR /app
