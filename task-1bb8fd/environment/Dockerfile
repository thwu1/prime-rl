FROM python:3.12-slim AS pcap-builder
WORKDIR /build
RUN pip install scapy==2.6.1
COPY generate_pcap.py /build/generate_pcap.py
RUN python3 /build/generate_pcap.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN echo 'wireshark-common wireshark-common/install-setuid boolean false' | debconf-set-selections && \
    DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y \
    tshark \
    tcpdump \
    suricata \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/lib/suricata/rules && \
    touch /var/lib/suricata/rules/suricata.rules

COPY --from=pcap-builder /build/incident.pcap /app/evidence/incident.pcap
COPY preliminary_report.json /app/evidence/preliminary_report.json
RUN mkdir -p /app/output
WORKDIR /app
