FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip python3 nftables jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY trace.log /app/trace.log
COPY conntrack.dump /app/conntrack.dump
COPY policy.yaml /app/policy.yaml
COPY nft_ruleset.conf /app/nft_ruleset.conf

WORKDIR /app
