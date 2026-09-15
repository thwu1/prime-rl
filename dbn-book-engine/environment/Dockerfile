FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip zstd xxd && \
    rm -rf /var/lib/apt/lists/*

COPY docs/ /app/docs/
COPY feeds/ /app/feeds/
COPY sample_data/symbology.json /app/symbology.json
COPY sample_data/checkpoints.json /app/checkpoints.json

RUN mkdir -p /app/output

WORKDIR /app
