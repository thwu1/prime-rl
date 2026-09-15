FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY simulation.g2o /app/data/simulation.g2o
COPY format_spec.txt /app/data/format_spec.txt

WORKDIR /app
