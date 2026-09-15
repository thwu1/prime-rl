FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /app/

RUN mkdir -p /app/output

WORKDIR /app
