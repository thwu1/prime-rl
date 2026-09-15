FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    libproj-dev \
    proj-data \
    && rm -rf /var/lib/apt/lists/*

COPY datasets/ /app/datasets/
COPY config.json /app/config.json
RUN mkdir -p /app/output
RUN ls -la /app/datasets/ && echo "Dataset file count:" && ls -1 /app/datasets/ | wc -l
