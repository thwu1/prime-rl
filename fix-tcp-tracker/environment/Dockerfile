FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y python3 python3-pip tshark && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install scapy==2.6.1

COPY generate_pcaps.py /tmp/generate_pcaps.py
RUN python3 /tmp/generate_pcaps.py && rm /tmp/generate_pcaps.py

COPY tcp_tracker.py /app/tcp_tracker.py

WORKDIR /app
