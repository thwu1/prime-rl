
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip python3-dev && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/manifests /app/proposed_changes

COPY manifests/ /app/manifests/
COPY queries.json /app/queries.json
COPY connectivity_requirements.json /app/connectivity_requirements.json
COPY output_schema.json /app/output_schema.json
COPY proposed_changes/ /app/proposed_changes/

WORKDIR /app
