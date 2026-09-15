FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip curl wget && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
WORKDIR /app

COPY scenarios.json /app/scenarios.json
COPY pipeline.py /app/pipeline.py
COPY kernels.tm /app/kernels.tm
