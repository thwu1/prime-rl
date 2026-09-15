
FROM python:3.12-slim AS pcap-builder

COPY generate_pcap.py /build/generate_pcap.py
RUN pip install scapy==2.6.1 && python3 /build/generate_pcap.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        tshark \
        tcpdump \
        python3-pip \
        xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY --from=pcap-builder /build/capture.pcap /app/capture.pcap

WORKDIR /app
