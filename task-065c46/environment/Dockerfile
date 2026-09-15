FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    libhdf5-dev \
    hdf5-tools \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY dpw_workshop_results.csv /tmp/dpw_workshop_results.csv
COPY generate_data.py /tmp/generate_data.py

RUN pip3 install --no-cache-dir h5py==3.12.1 numpy==2.1.3 && \
    python3 /tmp/generate_data.py && \
    pip3 uninstall h5py numpy -y && \
    rm /tmp/generate_data.py /tmp/dpw_workshop_results.csv

WORKDIR /app
