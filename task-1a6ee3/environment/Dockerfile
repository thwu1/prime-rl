FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

# Create task directory structure
RUN mkdir -p /app/captures /app/signatures

# Generate the PCAP file containing crafted TCP SYN packets
COPY gen_pcap.py /tmp/gen_pcap.py
RUN python3 /tmp/gen_pcap.py && rm /tmp/gen_pcap.py

# Copy fingerprint signature database
COPY tcp_syn.fp /app/signatures/tcp_syn.fp

WORKDIR /app
