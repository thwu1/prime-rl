FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    hdf5-tools \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 h5py==3.12.1

COPY generate_pipeline.py /tmp/generate_pipeline.py
RUN python3 /tmp/generate_pipeline.py && rm /tmp/generate_pipeline.py
