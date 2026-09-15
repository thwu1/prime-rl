FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
    python3-pip \
    tshark \
    tcpdump \
    nmap \
    net-tools \
    jq \
    dnsutils \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install scapy==2.6.1

RUN mkdir -p /app/proposed_rules

COPY candidate_rules.txt /app/proposed_rules/candidate_rules.txt

COPY gen_pcap.py /tmp/gen_pcap.py
RUN python3 /tmp/gen_pcap.py && rm -f /tmp/gen_pcap.py

WORKDIR /app
