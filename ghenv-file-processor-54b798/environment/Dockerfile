FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3-pip \
    jq \
    sqlite3 \
    openssl \
    && rm -rf /var/lib/apt/lists/*

COPY runner-env.sh /app/runner-env.sh
RUN chmod +x /app/runner-env.sh

WORKDIR /app

