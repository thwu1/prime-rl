FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip libffi-dev && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/output

COPY scrambles.json /app/scrambles.json
COPY fmc_results.tsv /app/fmc_results.tsv
COPY invalid_states.json /app/invalid_states.json
COPY cubie_conventions.json /app/cubie_conventions.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 kociemba==1.2.1
