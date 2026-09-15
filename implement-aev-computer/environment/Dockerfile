FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip hdf5-tools sqlite3 && rm -rf /var/lib/apt/lists/*

COPY params.txt /app/params.txt
COPY conformations.json /app/conformations.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==1.26.4 h5py==3.11.0
