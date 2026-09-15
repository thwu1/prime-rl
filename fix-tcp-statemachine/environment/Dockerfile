FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip tshark jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/tcp_sim /app/reference /app/scenarios

COPY tcp_sim/__init__.py /app/tcp_sim/__init__.py
COPY tcp_sim/segment.py /app/tcp_sim/segment.py
COPY tcp_sim/connection.py /app/tcp_sim/connection.py
COPY tcp_sim/network.py /app/tcp_sim/network.py

COPY gen_pcap.py /tmp/gen_pcap.py
RUN python3 /tmp/gen_pcap.py && rm /tmp/gen_pcap.py

COPY scenarios/config.json /app/scenarios/config.json
COPY run_sim.py /app/run_sim.py

WORKDIR /app
