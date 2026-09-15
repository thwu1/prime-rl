FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip libxml2-utils && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY device.svd /app/device.svd
COPY hwref.txt /app/hwref.txt
COPY proposed_codegen.json /app/proposed_codegen.json
WORKDIR /app
