FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        nodejs \
        npm \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /tests /solution /logs/verifier

COPY src/ /app/src/
COPY package.json /app/package.json
COPY tsconfig.json /app/tsconfig.json

WORKDIR /app
