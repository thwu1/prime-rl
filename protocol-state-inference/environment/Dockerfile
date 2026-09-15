FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    graphviz \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY config.json /app/config.json
COPY generate_traces.py /tmp/generate_traces.py
RUN python3 /tmp/generate_traces.py && rm /tmp/generate_traces.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 scipy==1.14.1
