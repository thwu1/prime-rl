FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip jq sqlite3 gnuplot-nox && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/traces

COPY moesi_sim.py /app/moesi_sim.py
COPY topology.json /app/topology.json
COPY diagnostic.trace /app/diagnostic.trace
COPY traces/ /app/traces/

WORKDIR /app
