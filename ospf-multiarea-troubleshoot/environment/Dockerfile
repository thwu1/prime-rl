FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/configs

COPY ospf_checker.py /app/ospf_checker.py
COPY topology.json /app/topology.json
COPY R1.conf /app/configs/R1.conf
COPY R2.conf /app/configs/R2.conf
COPY R3.conf /app/configs/R3.conf
COPY R4.conf /app/configs/R4.conf
COPY R5.conf /app/configs/R5.conf
COPY R6.conf /app/configs/R6.conf

RUN chmod +x /app/ospf_checker.py

WORKDIR /app
