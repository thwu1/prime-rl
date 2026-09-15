FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        python3-yaml \
        graphviz \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/traffic /app/coverage

COPY app/api_spec.yaml /app/api_spec.yaml
COPY app/traffic/ /app/traffic/
COPY app/coverage/ /app/coverage/

WORKDIR /app
