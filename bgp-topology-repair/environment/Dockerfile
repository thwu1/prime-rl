FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y \
        frr \
        frr-pythontools \
        iproute2 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/configs /app/diagnostics

COPY configs/r1.conf /app/configs/r1.conf
COPY configs/r2.conf /app/configs/r2.conf
COPY configs/r3.conf /app/configs/r3.conf
COPY configs/r4.conf /app/configs/r4.conf
COPY configs/r5.conf /app/configs/r5.conf

COPY diagnostics/incident_report.txt /app/diagnostics/incident_report.txt
COPY diagnostics/network_policy.txt /app/diagnostics/network_policy.txt
COPY diagnostics/design_notes.txt /app/diagnostics/design_notes.txt

WORKDIR /app
