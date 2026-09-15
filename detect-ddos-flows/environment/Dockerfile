FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y \
    python3 python3-pip sqlite3 jq tshark \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/output /app/captures

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm -f /tmp/generate_data.py && rm -rf /tmp/__pycache__

WORKDIR /app
