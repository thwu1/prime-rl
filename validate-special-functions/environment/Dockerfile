FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install mpmath==1.3.0

COPY gen_table.py /tmp/gen_table.py
RUN mkdir -p /app && python3 /tmp/gen_table.py && rm /tmp/gen_table.py

WORKDIR /app
