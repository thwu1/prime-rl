FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    socat \
    tcpdump \
    netcat-openbsd \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY protocol.md /app/protocol.md
COPY authority_server.py /app/authority_server.py
COPY site_config.json /app/site_config.json
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh /app/authority_server.py

WORKDIR /app
