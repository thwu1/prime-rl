FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install h5py==3.12.1 numpy==2.1.3 -q
RUN mkdir -p /app/data
COPY create_data.py /tmp/create_data.py
RUN python3 /tmp/create_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    hdf5-tools \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results

COPY --from=builder /app/data/transport_data.h5 /app/data/transport_data.h5
COPY mission.json /app/data/mission.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
