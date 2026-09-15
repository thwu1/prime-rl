FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && \
    apt-get install -y redis-server redis-tools python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/conf /app/data/node0 /app/data/node1 /app/data/node2

COPY conf/node-7000.conf /app/conf/node-7000.conf
COPY conf/node-7001.conf /app/conf/node-7001.conf
COPY conf/node-7002.conf /app/conf/node-7002.conf
COPY dataset.csv /app/dataset.csv
COPY alerts.log /app/alerts.log
COPY setup_cluster.py /tmp/setup_cluster.py

RUN python3 /tmp/setup_cluster.py && rm -f /tmp/setup_cluster.py

WORKDIR /app
