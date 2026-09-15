FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Enable universe repository (needed for GMT) and install dependencies
RUN if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then \
        grep -q 'universe' /etc/apt/sources.list.d/ubuntu.sources || \
        sed -i 's/^Components: .*/& universe/' /etc/apt/sources.list.d/ubuntu.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
        grep -q 'universe' /etc/apt/sources.list || \
        echo "deb http://archive.ubuntu.com/ubuntu noble universe" >> /etc/apt/sources.list; \
    fi && \
    apt-get update && \
    apt-get install -y python3-pip gmt && \
    rm -rf /var/lib/apt/lists/*

# Generate synthetic ship track bathymetry data
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

RUN mkdir -p /app/results
WORKDIR /app

