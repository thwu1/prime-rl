FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 scipy==1.13.1 h5py==3.11.0 -q

# Compile incomplete thermal model as shared library
COPY thermal_model.c thermal_model.h /tmp/build/
RUN mkdir -p /app/lib && \
    gcc -shared -fPIC -O2 -o /app/lib/thermal_model.so /tmp/build/thermal_model.c -lm && \
    cp /tmp/build/thermal_model.h /app/lib/ && \
    rm -rf /tmp/build

# Generate reference measurement data in HDF5 format
COPY generate_data.py /tmp/generate_data.py
RUN mkdir -p /app/data && python3 /tmp/generate_data.py && rm /tmp/generate_data.py

# System configuration
COPY config.yaml /app/config.yaml

WORKDIR /app
