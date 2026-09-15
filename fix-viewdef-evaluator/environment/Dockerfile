FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip nodejs npm && \
    rm -rf /var/lib/apt/lists/*

COPY package.json /app/package.json
COPY package-lock.json /app/package-lock.json
COPY tsconfig.json /app/tsconfig.json
COPY src/ /app/src/
COPY runner.ts /app/runner.ts
COPY fixtures/ /app/fixtures/

WORKDIR /app
