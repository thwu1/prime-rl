FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    verilator \
    yosys \
    g++ make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY hazard.sv /app/hazard.sv
COPY gen_trace.py /app/gen_trace.py
COPY schema.json /app/schema.json

RUN python3 /app/gen_trace.py && rm /app/gen_trace.py

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
