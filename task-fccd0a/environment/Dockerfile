FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y --no-install-recommends python3-pip tshark tcpdump && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY baseline_classifier.py /app/baseline_classifier.py
COPY generate_data.py /app/generate_data.py

RUN python3 /app/generate_data.py && rm /app/generate_data.py

