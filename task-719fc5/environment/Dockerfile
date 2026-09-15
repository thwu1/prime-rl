FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/docs

COPY nav2_params.yaml /app/nav2_params.yaml
COPY docs/architecture.md /app/docs/architecture.md
COPY docs/costmap_reference.md /app/docs/costmap_reference.md
COPY docs/mppi_reference.md /app/docs/mppi_reference.md
COPY docs/filter_reference.md /app/docs/filter_reference.md

WORKDIR /app
