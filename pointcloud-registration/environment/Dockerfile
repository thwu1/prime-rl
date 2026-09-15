FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    hdf5-tools \
    libhdf5-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 scipy==1.13.1 h5py==3.11.0

COPY generate_data.py /tmp/generate_data.py
COPY broken_pipeline.py /app/pipeline/attempt.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

RUN mkdir -p /app/output
WORKDIR /app
