FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN echo 'wireshark-common wireshark-common/install-setuid boolean false' | debconf-set-selections
RUN apt-get update && apt-get install -y --no-install-recommends python3-pip python3 sqlite3 tshark jq && rm -rf /var/lib/apt/lists/*

COPY app/ /app/
COPY setup_db.py /tmp/setup_db.py
COPY generate_pcap.py /tmp/generate_pcap.py
RUN python3 /tmp/setup_db.py && python3 /tmp/generate_pcap.py && rm /tmp/setup_db.py /tmp/generate_pcap.py

WORKDIR /app

