
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    jq \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/audit-logs /app/cluster-state /app/results/remediation

COPY audit-log.json /app/audit-logs/kube-apiserver-audit.json
COPY current-rbac.yaml /app/cluster-state/current-rbac.yaml
COPY current-workloads.yaml /app/cluster-state/current-workloads.yaml

WORKDIR /app
