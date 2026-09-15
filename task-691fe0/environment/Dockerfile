FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4

COPY setup_data.py /opt/setup_data.py
RUN python3 /opt/setup_data.py && \
    test -f /data/raw_data/MODEL-A/metadata.json && \
    test -f /data/raw_data/MODEL-B/metadata.json && \
    test -f /data/raw_data/MODEL-C/metadata.json && \
    echo "Data generation verified successfully"

WORKDIR /app
