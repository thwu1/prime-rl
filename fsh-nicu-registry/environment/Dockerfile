FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends nodejs npm python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/input/fsh

COPY sushi-config.yaml /app/sushi-config.yaml
COPY aliases.fsh /app/input/fsh/aliases.fsh
COPY rulesets.fsh /app/input/fsh/rulesets.fsh
COPY profiles.fsh /app/input/fsh/profiles.fsh
COPY extensions.fsh /app/input/fsh/extensions.fsh
COPY terminology.fsh /app/input/fsh/terminology.fsh

