FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && \
    apt-get install -y python3 python3-pip tshark && \
    rm -rf /var/lib/apt/lists/*

COPY generate_pcap.py /tmp/generate_pcap.py
RUN python3 /tmp/generate_pcap.py && rm /tmp/generate_pcap.py

COPY lb_skeleton.py /app/lb_processor.py

WORKDIR /app
