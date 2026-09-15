FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3-pip python3-dev build-essential cmake git pkg-config && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==2.1.3 pyEQL==1.5.0
