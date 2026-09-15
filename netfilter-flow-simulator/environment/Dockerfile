FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tshark \
    tcpdump \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install scapy==2.5.0

RUN mkdir -p /app/incidents /app/results

COPY incidents/ /app/incidents/
COPY gen_pcaps.py /tmp/gen_pcaps.py
RUN python3 /tmp/gen_pcaps.py && rm /tmp/gen_pcaps.py

WORKDIR /app
