
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install PyYAML==6.0.2

WORKDIR /app

COPY manifests/ /app/manifests/
COPY queries.json /app/queries.json
COPY SCHEMA.md /app/SCHEMA.md
COPY rbac_audit.py /app/rbac_audit.py
COPY validate.py /app/validate.py
