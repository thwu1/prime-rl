FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip python3-dev hdf5-tools && \
    rm -rf /var/lib/apt/lists/*

COPY benchmarks/ /app/benchmarks/
COPY generate_statepoints.py /tmp/generate_statepoints.py

RUN pip3 install h5py==3.11.0 numpy==1.26.4 -q && \
    python3 /tmp/generate_statepoints.py && \
    rm /tmp/generate_statepoints.py && \
    pip3 uninstall -y h5py numpy

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 h5py==3.11.0 numpy==1.26.4
