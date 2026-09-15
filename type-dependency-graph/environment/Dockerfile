FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y nodejs npm python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package.json
COPY tsconfig.json tsconfig.json
COPY src/analyzer.ts src/analyzer.ts

COPY target-project/tsconfig.json target-project/tsconfig.json
COPY target-project/src/core.ts target-project/src/core.ts
COPY target-project/src/models.ts target-project/src/models.ts
COPY target-project/src/services.ts target-project/src/services.ts
COPY target-project/src/utils.ts target-project/src/utils.ts
COPY target-project/src/events.ts target-project/src/events.ts
COPY target-project/src/registry.ts target-project/src/registry.ts
