
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY interface.proto /app/interface.proto
COPY train_data.json /app/train_data.json
COPY test_data.json /app/test_data.json
COPY SPEC.md /app/SPEC.md
