FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/grammar /app/src/generated

COPY app/package.json /app/package.json
COPY app/tsconfig.json /app/tsconfig.json
COPY app/grammar/sql.pegjs /app/grammar/sql.pegjs
COPY app/src/types.ts /app/src/types.ts
COPY app/src/index.ts /app/src/index.ts
COPY app/src/stringify.ts /app/src/stringify.ts
COPY app/src/transform.ts /app/src/transform.ts
COPY app/src/generated/.gitkeep.ts /app/src/generated/.gitkeep.ts

WORKDIR /app

