FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    proj-bin \
    proj-data \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY scenario_a.gie scenario_b.gie scenario_c.gie scenario_d.gie /app/
COPY chain_input.csv /app/

RUN mkdir -p /app/results

WORKDIR /app
