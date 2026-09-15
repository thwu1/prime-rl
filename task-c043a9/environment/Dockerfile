FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/audit-logs /app/findings

COPY generate_audit_data.py /tmp/generate_audit_data.py
RUN python3 /tmp/generate_audit_data.py && rm /tmp/generate_audit_data.py

WORKDIR /app
