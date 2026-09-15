
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip wireguard-tools xxd jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY generate_env.py /tmp/generate_env.py
COPY derp_spec.txt /app/derp_protocol_spec.txt

RUN python3 /tmp/generate_env.py && rm /tmp/generate_env.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
