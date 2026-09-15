
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections && \
    apt-get update && \
    apt-get install -y python3 python3-pip tshark dnsutils xxd && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY zone.db /app/zone.db
COPY broken_server.py /app/dns_server.py
COPY generate_captures.py /tmp/generate_captures.py

RUN python3 /tmp/generate_captures.py && rm /tmp/generate_captures.py

WORKDIR /app
