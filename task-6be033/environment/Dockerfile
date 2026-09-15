FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY woa_sim.py /usr/local/bin/woa-sim
RUN chmod +x /usr/local/bin/woa-sim

COPY game_engine.py /app/game_engine.py
COPY schema.sql /app/schema.sql
COPY config_template.toml /app/config_template.toml

RUN mkdir -p /app/results

WORKDIR /app
