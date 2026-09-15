FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    iperf3 \
    openssl \
    jq \
    python3-pip \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/captures /app/advisories /app/auth

COPY tcp_single.json /app/captures/
COPY udp_test.json /app/captures/
COPY tcp_parallel.json /app/captures/
COPY tcp_bidir.json /app/captures/

COPY advisory_cve-2023-38403.txt /app/advisories/
COPY advisory_cve-2024-26306.txt /app/advisories/
COPY advisory_cve-2024-53580.txt /app/advisories/
COPY advisory_cve-2025-54351.txt /app/advisories/

COPY deployment_info.json /app/
COPY report_schema.json /app/
COPY classification_thresholds.json /app/

WORKDIR /app
