
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/reference

COPY twai_filter.rs /app/reference/twai_filter.rs
COPY test_vectors.json /app/test_vectors.json
COPY gen_register_dump.py /tmp/gen_register_dump.py
RUN python3 /tmp/gen_register_dump.py && rm /tmp/gen_register_dump.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
