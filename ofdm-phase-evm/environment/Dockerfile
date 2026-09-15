
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/specs

COPY config.yaml /app/config.yaml
COPY specs/api.md /app/specs/api.md
COPY specs/output_format.md /app/specs/output_format.md

WORKDIR /app
