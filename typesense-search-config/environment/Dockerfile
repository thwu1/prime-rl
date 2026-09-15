FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y curl jq python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/ts.tar.gz https://dl.typesense.org/releases/27.1/typesense-server-27.1-linux-amd64.tar.gz && \
    tar xzf /tmp/ts.tar.gz -C /usr/local/bin/ && \
    chmod +x /usr/local/bin/typesense-server && \
    rm -f /tmp/ts.tar.gz /usr/local/bin/typesense-server.md5.txt && \
    test -x /usr/local/bin/typesense-server

RUN mkdir -p /app/data /app/typesense-data

COPY data/brands.jsonl /app/data/brands.jsonl
COPY data/products.jsonl /app/data/products.jsonl
COPY data/reviews.jsonl /app/data/reviews.jsonl

COPY setup_broken.sh /tmp/setup_broken.sh
RUN chmod +x /tmp/setup_broken.sh && /tmp/setup_broken.sh && rm -f /tmp/setup_broken.sh

WORKDIR /app
