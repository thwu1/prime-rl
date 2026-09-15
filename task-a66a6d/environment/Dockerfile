FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip jq sqlite3 graphviz && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/cosmos_ref /app/jq_filters /app/output

COPY manifest.json /app/manifest.json
COPY orchestrator.py /app/orchestrator.py
COPY cosmos_ref/selector.py /app/cosmos_ref/selector.py
COPY cosmos_ref/constants.py /app/cosmos_ref/constants.py

WORKDIR /app
