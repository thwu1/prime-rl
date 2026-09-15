FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    apache2-utils \
    openssl \
    python3 \
    python3-pip \
    python3-yaml \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sL "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv5.4.3/kustomize_v5.4.3_linux_amd64.tar.gz" | tar xz -C /usr/local/bin/

WORKDIR /app

COPY spec.yaml /app/spec.yaml
COPY notes.md /app/notes.md
COPY broken/ /app/broken/
COPY setup_broken.sh /tmp/setup_broken.sh
RUN chmod +x /tmp/setup_broken.sh && /tmp/setup_broken.sh && rm /tmp/setup_broken.sh

RUN mkdir -p /app/output/rbac /app/output/network-policies /app/output/quotas \
    /app/output/limit-ranges /app/output/tls /app/output/routes /app/output/scc
