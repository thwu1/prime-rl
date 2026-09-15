FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip curl ca-certificates && \
    curl -fsSL https://nodejs.org/dist/v20.18.0/node-v20.18.0-linux-x64.tar.gz -o /tmp/node.tar.gz && \
    tar -xzf /tmp/node.tar.gz -C /usr/local --strip-components=1 && \
    rm -f /tmp/node.tar.gz && \
    rm -rf /var/lib/apt/lists/*

COPY lox_reference.py /app/lox.py

WORKDIR /app
