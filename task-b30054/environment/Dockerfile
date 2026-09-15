FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/manifests

COPY manifests/namespace.yaml /app/manifests/namespace.yaml
COPY manifests/configmap.yaml /app/manifests/configmap.yaml
COPY manifests/secrets.yaml /app/manifests/secrets.yaml
COPY manifests/serviceaccount.yaml /app/manifests/serviceaccount.yaml
COPY manifests/frontend.yaml /app/manifests/frontend.yaml
COPY manifests/api-server.yaml /app/manifests/api-server.yaml
COPY manifests/worker.yaml /app/manifests/worker.yaml
COPY manifests/pv-pvc.yaml /app/manifests/pv-pvc.yaml
COPY manifests/networkpolicy.yaml /app/manifests/networkpolicy.yaml
COPY manifests/cronjob.yaml /app/manifests/cronjob.yaml
COPY manifests/rbac.yaml /app/manifests/rbac.yaml
COPY manifests/hpa.yaml /app/manifests/hpa.yaml

RUN test $(ls /app/manifests/*.yaml | wc -l) -eq 12

WORKDIR /app
