FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install stim==1.14.0

RUN mkdir -p /app/circuits

COPY gen_circuits.py /tmp/gen_circuits.py
RUN python3 /tmp/gen_circuits.py && rm /tmp/gen_circuits.py

COPY decoder.py /app/decoder.py
COPY benchmark.py /app/benchmark.py
COPY config.json /app/config.json
COPY results_schema.json /app/results_schema.json

WORKDIR /app
