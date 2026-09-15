FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        glpk-utils \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/instances /app/solutions /app/models

COPY instances/ /app/instances/

WORKDIR /app
