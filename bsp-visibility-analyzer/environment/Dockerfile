FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip graphviz && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY format_spec.txt /app/format_spec.txt
COPY gen_map.py /tmp/gen_map.py
RUN python3 /tmp/gen_map.py && rm /tmp/gen_map.py

WORKDIR /app
