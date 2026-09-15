FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install etcd v3.5.12 (provides etcd, etcdctl, etcdutl)
RUN curl -L https://github.com/etcd-io/etcd/releases/download/v3.5.12/etcd-v3.5.12-linux-amd64.tar.gz -o /tmp/etcd.tar.gz && \
    tar xzf /tmp/etcd.tar.gz --no-same-owner -C /tmp && \
    mv /tmp/etcd-v3.5.12-linux-amd64/etcd /usr/local/bin/ && \
    mv /tmp/etcd-v3.5.12-linux-amd64/etcdctl /usr/local/bin/ && \
    mv /tmp/etcd-v3.5.12-linux-amd64/etcdutl /usr/local/bin/ && \
    rm -rf /tmp/etcd*

ENV ETCDCTL_API=3

WORKDIR /app

COPY data/ /app/data/
COPY spec.md /app/spec.md
