FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip g++ build-essential make && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/instances /app/tools /app/docs

COPY instances/instance_001.gr /app/instances/instance_001.gr
COPY instances/instance_002.gr /app/instances/instance_002.gr
COPY instances/instance_003.gr /app/instances/instance_003.gr
COPY instances/instance_004.gr /app/instances/instance_004.gr
COPY instances/instance_005.gr /app/instances/instance_005.gr
COPY instances/instance_006.gr /app/instances/instance_006.gr
COPY instances/instance_007.gr /app/instances/instance_007.gr
COPY instances/instance_008.gr /app/instances/instance_008.gr

COPY tools/verify_tww.py /app/tools/verify_tww
RUN chmod +x /app/tools/verify_tww

COPY docs/format_reference.txt /app/docs/format_reference.txt
COPY docs/approach_notes.txt /app/docs/approach_notes.txt

WORKDIR /app
