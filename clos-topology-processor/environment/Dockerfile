FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

RUN mkdir -p /app/topologies /app/reference

COPY resolver.py /app/resolver.py
COPY types_topology.go /app/reference/types_topology.go
COPY basic.flat.yml /app/topologies/basic.flat.yml
COPY mixed.flat.yml /app/topologies/mixed.flat.yml
COPY tricky.flat.yml /app/topologies/tricky.flat.yml

WORKDIR /app
