FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

COPY config.sh /app/config.sh
COPY pipeline.sh /app/pipeline.sh
COPY process.sh /app/process.sh
COPY archive.sh /app/archive.sh
COPY analyze.sh /app/analyze.sh
COPY header.txt /app/header.txt
COPY input/server1.log /app/input/server1.log
COPY input/server2.log /app/input/server2.log
COPY input/server3.log /app/input/server3.log

RUN chmod +x /app/config.sh /app/pipeline.sh /app/process.sh /app/archive.sh /app/analyze.sh

WORKDIR /app
