FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get install -y xxd netcat-openbsd || true && \
    rm -rf /var/lib/apt/lists/*

COPY generate_logs.py /tmp/generate_logs.py
COPY format_reference.txt /app/format_reference.txt
COPY wire_reference.txt /app/wire_reference.txt

RUN python3 /tmp/generate_logs.py && rm /tmp/generate_logs.py

WORKDIR /app
