FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/conf/roles /app/conf/norms

COPY massim_spec.md /app/massim_spec.md
COPY conf/config.json /app/conf/config.json
COPY conf/roles/standard.json /app/conf/roles/standard.json
COPY conf/norms/standard.json /app/conf/norms/standard.json
COPY scenario.json /app/scenario.json
COPY action_log.json /app/action_log.json

WORKDIR /app
