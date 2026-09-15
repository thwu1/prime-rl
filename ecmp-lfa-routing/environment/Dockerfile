
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y python3 python3-pip tshark graphviz && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY gen_capture.py /tmp/gen_capture.py
RUN python3 /tmp/gen_capture.py && rm /tmp/gen_capture.py

COPY routing_engine.py /app/routing_engine.py
COPY protocol_spec.txt /app/protocol_spec.txt
COPY routing_policy.json /app/routing_policy.json

WORKDIR /app
