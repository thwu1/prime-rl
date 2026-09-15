
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip frr frr-pythontools jq iproute2 && rm -rf /var/lib/apt/lists/*

# Enable bgpd and zebra daemons, set up FRR directories with correct permissions
RUN sed -i 's/bgpd=no/bgpd=yes/' /etc/frr/daemons && \
    sed -i 's/zebra=no/zebra=yes/' /etc/frr/daemons && \
    echo "" > /etc/frr/frr.conf && \
    mkdir -p /var/run/frr /var/log/frr && \
    chown -R frr:frr /var/run/frr /var/log/frr /etc/frr

WORKDIR /app

COPY configs/ /app/configs/
COPY topology.json /app/topology.json
COPY requirements.json /app/requirements.json
COPY start_frr.sh /app/start_frr.sh
RUN chmod +x /app/start_frr.sh

RUN mkdir -p /app/output/corrected
