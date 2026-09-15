FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    echo 'wireshark-common wireshark-common/install-setuid boolean false' | debconf-set-selections && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip tshark sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/captures /app/output /app/tools

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY SPEC.md /app/data/SPEC.md

WORKDIR /app
