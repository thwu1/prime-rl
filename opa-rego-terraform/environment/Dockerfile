FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    jq \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -L -o /usr/local/bin/opa https://openpolicyagent.org/downloads/v0.70.0/opa_linux_amd64_static && \
    chmod +x /usr/local/bin/opa

RUN mkdir -p /app/plans /app/policies

COPY plans/ /app/plans/
COPY manifest.json /app/manifest.json

WORKDIR /app
