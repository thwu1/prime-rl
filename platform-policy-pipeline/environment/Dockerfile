
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        curl \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN curl -L -o /usr/local/bin/opa \
    https://github.com/open-policy-agent/opa/releases/download/v0.70.0/opa_linux_amd64_static && \
    chmod +x /usr/local/bin/opa

COPY app/ /app/

WORKDIR /app
