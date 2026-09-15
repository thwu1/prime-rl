FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY option_chain.csv /app/data/option_chain.csv
COPY exotic_specs.json /app/data/exotic_specs.json
COPY portfolio.json /app/data/portfolio.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==1.26.4 scipy==1.13.1
