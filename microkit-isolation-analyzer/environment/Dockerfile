
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip graphviz && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY system.xml /app/system.xml
COPY policy.json /app/policy.json
COPY certification_report.md /app/certification_report.md
COPY analyzer.py /app/analyzer.py
COPY osmosis_spec.md /app/osmosis_spec.md

WORKDIR /app
