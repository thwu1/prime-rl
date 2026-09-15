FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y golang-go python3-pip && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY thermodb.json /app/thermodb.json
COPY problems /app/problems

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 pyyaml==6.0.2
