FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-numpy \
    python3-h5py \
    hdf5-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY schema.json /app/schema.json
COPY config.toml /app/config.toml
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py
