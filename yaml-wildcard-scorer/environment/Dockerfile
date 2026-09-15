FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip python3-yaml jq curl && rm -rf /var/lib/apt/lists/*

RUN curl -sL https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv5.4.3/kustomize_v5.4.3_linux_amd64.tar.gz | tar xz -C /usr/local/bin/

RUN curl -sL https://github.com/mikefarah/yq/releases/download/v4.44.3/yq_linux_amd64 -o /usr/local/bin/yq && chmod +x /usr/local/bin/yq

RUN mkdir -p /app/output

COPY SPEC.md /app/SPEC.md
COPY audit.yaml /app/audit.yaml
COPY kustomize /app/kustomize
COPY live /app/live

WORKDIR /app
