FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip jq && rm -rf /var/lib/apt/lists/*

COPY sail_sources/ /app/sail_sources/
COPY configs/ /app/configs/

RUN mkdir -p /app/output

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
