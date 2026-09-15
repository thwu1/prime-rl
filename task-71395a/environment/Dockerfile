FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/shapes /app/output

COPY registry.json /app/registry.json
COPY dcat-ap-301.ttl /app/shapes/dcat-ap-301.ttl

WORKDIR /app
