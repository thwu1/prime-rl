FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip jq graphviz && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/spec

COPY spec/port_types.json /app/spec/port_types.json
COPY spec/components.json /app/spec/components.json
COPY spec/topology.json /app/spec/topology.json
COPY spec/runtime.json /app/spec/runtime.json
COPY spec/requirements.md /app/spec/requirements.md
COPY spec/fpp_rules.md /app/spec/fpp_rules.md

WORKDIR /app
