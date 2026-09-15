FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN git config --global user.name "test" && \
    git config --global user.email "test@test.local" && \
    git config --global init.defaultBranch main

COPY manifest.json /app/manifest.json
COPY spec.md /app/spec.md
COPY vintages/ /app/vintages/
COPY expected/ /app/expected/
COPY backfill.py /app/backfill.py

WORKDIR /app
