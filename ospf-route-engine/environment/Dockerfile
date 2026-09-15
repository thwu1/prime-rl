FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install scapy==2.5.0
RUN mkdir -p /app
COPY generate_pcap.py /tmp/generate_pcap.py
RUN python3 /tmp/generate_pcap.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y python3 python3-pip tshark tcpdump && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app
COPY --from=builder /app/ospf_capture.pcap /app/ospf_capture.pcap
WORKDIR /app
