FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/src/__tests__
COPY app/package.json /app/package.json
COPY app/tsconfig.json /app/tsconfig.json
COPY app/vitest.config.ts /app/vitest.config.ts
COPY app/src/types.ts /app/src/types.ts
COPY app/src/url.ts /app/src/url.ts
COPY app/src/router.ts /app/src/router.ts
COPY app/src/type-checks.ts /app/src/type-checks.ts
COPY app/src/__tests__/url.test.ts /app/src/__tests__/url.test.ts
COPY app/src/__tests__/router.test.ts /app/src/__tests__/router.test.ts

WORKDIR /app
