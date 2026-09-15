FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    nodejs npm python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src

COPY package.json /app/package.json
COPY tsconfig.json /app/tsconfig.json
COPY src/types.ts /app/src/types.ts
COPY src/stages.ts /app/src/stages.ts
COPY src/compensation.ts /app/src/compensation.ts
COPY src/pipeline.ts /app/src/pipeline.ts

WORKDIR /app
