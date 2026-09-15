FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip jq curl && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://get.helm.sh/helm-v3.16.4-linux-amd64.tar.gz -o /tmp/helm.tar.gz && \
    tar -xzf /tmp/helm.tar.gz -C /tmp && \
    mv /tmp/linux-amd64/helm /usr/local/bin/helm && \
    rm -rf /tmp/helm.tar.gz /tmp/linux-amd64

COPY app/ /app/

WORKDIR /app
