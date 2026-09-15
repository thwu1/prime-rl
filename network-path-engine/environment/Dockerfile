
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections && \
    apt-get update && \
    apt-get install -y python3 python3-pip tshark && \
    rm -rf /var/lib/apt/lists/*

COPY gen_pcaps.py /tmp/gen_pcaps.py

RUN pip3 install scapy==2.6.1 -q && \
    python3 /tmp/gen_pcaps.py && \
    pip3 uninstall -y scapy && \
    rm -f /tmp/gen_pcaps.py

COPY topology.json /app/topology.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
