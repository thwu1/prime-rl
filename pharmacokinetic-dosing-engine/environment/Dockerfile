FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip jq xmlstarlet && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/output

COPY drugbank_excerpt.xml /app/drugbank_excerpt.xml
COPY dosing_scenarios.json /app/dosing_scenarios.json
COPY curated_reference.tsv /app/curated_reference.tsv


WORKDIR /app
