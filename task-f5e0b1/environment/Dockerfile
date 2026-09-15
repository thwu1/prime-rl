FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    openssl \
    libssl-dev \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install cryptography==44.0.0 -q

# iperf3 authentication source code for analysis
COPY iperf_auth.c /app/iperf3_auth_src/iperf_auth.c
COPY iperf_auth.h /app/iperf3_auth_src/iperf_auth.h
COPY t_auth.c /app/iperf3_auth_src/t_auth.c

# ESnet security advisories
COPY advisory_cve_2024_26306.txt /app/advisories/advisory_cve_2024_26306.txt
COPY advisory_cve_2024_53580.txt /app/advisories/advisory_cve_2024_53580.txt
COPY advisory_cve_2025_54349.txt /app/advisories/advisory_cve_2025_54349.txt
COPY advisory_cve_2025_54350.txt /app/advisories/advisory_cve_2025_54350.txt

# Server deployment configuration
COPY server_config.json /app/server_config.json

# Generate forensic test data and remove the generator
COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

WORKDIR /app
