
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

WORKDIR /app
COPY generate_data.py /opt/generate_data.py
RUN python3 /opt/generate_data.py && \
    cp /app/dataset.npy /opt/dataset_backup.npy && \
    test -f /app/dataset.npy
