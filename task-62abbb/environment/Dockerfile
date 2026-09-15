FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip python3 jq graphviz && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY generate_manifest.py /tmp/generate_manifest.py
COPY queries.json /app/queries.json
COPY selectors.yml /app/selectors.yml

RUN python3 /tmp/generate_manifest.py && rm /tmp/generate_manifest.py
