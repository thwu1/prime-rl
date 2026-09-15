FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/docs

COPY pipeline.yaml /app/pipeline.yaml
COPY docs/config_format.md /app/docs/config_format.md
COPY docs/operational_notes.md /app/docs/operational_notes.md

WORKDIR /app
