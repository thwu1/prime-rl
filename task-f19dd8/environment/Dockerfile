FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq xxd && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/examples

COPY schema.sql /app/schema.sql
COPY FORMAT.md /app/FORMAT.md
COPY BINARY_FORMAT.md /app/BINARY_FORMAT.md
COPY setup_example.py /tmp/setup_example.py
RUN python3 /tmp/setup_example.py && rm /tmp/setup_example.py
COPY example_output.json /app/examples/example_output.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
