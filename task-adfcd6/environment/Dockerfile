
FROM python:3.12-slim AS generator
COPY generate_dns_log.py /tmp/generate_dns_log.py
RUN python3 /tmp/generate_dns_log.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        python3-dev \
        tshark \
        jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY --from=generator /tmp/dns_queries.log /app/dns_queries.log
COPY incident_report.txt /app/incident_report.txt

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
