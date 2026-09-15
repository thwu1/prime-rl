FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip libglib2.0-0 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY intrinsics.json /app/data/intrinsics.json
COPY observations.json /app/data/observations.json

WORKDIR /app
