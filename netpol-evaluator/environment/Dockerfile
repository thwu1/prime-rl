FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip curl jq && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

RUN curl -sL "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv5.0.0/kustomize_v5.0.0_linux_amd64.tar.gz" -o /tmp/kustomize.tar.gz && \
    tar xzf /tmp/kustomize.tar.gz -C /usr/local/bin/ && \
    rm /tmp/kustomize.tar.gz

RUN curl -sL "https://github.com/mikefarah/yq/releases/download/v4.30.8/yq_linux_amd64" -o /usr/local/bin/yq && \
    chmod +x /usr/local/bin/yq

RUN mkdir -p /app/manifests

COPY manifests/ /app/manifests/
COPY broken_evaluator.py /app/netpol-eval

RUN chmod +x /app/netpol-eval

WORKDIR /app
