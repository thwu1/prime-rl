
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PYTHONPATH=/app

RUN apt-get update && \
    apt-get install -y python3 python3-pip jq haproxy curl unzip && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://releases.hashicorp.com/consul/1.17.1/consul_1.17.1_linux_amd64.zip -o /tmp/consul.zip && \
    unzip /tmp/consul.zip -d /usr/local/bin/ && \
    rm /tmp/consul.zip && \
    chmod +x /usr/local/bin/consul

COPY app/ /app/

RUN chmod +x /app/pipeline.sh

WORKDIR /app
