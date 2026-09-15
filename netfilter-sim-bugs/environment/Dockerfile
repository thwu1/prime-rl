FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-scapy tshark jq && \
    rm -rf /var/lib/apt/lists/*

COPY netfilter_sim.py /app/netfilter_sim.py
COPY run_sim.py /app/run_sim.py
COPY evaluate.py /app/evaluate.py
COPY scenarios/ /app/scenarios/
COPY strategies/ /app/strategies/

COPY generate_traffic_mix.py /tmp/generate_traffic_mix.py
RUN python3 /tmp/generate_traffic_mix.py && rm /tmp/generate_traffic_mix.py

WORKDIR /app
