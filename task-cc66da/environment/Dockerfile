
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    graphviz \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sL "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv5.4.3/kustomize_v5.4.3_linux_amd64.tar.gz" -o /tmp/kustomize.tar.gz && \
    tar xzf /tmp/kustomize.tar.gz -C /usr/local/bin/ && \
    rm /tmp/kustomize.tar.gz && \
    chmod +x /usr/local/bin/kustomize

WORKDIR /app

COPY manifests/ /app/manifests/
