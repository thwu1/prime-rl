FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/src/types /app/tests
COPY app/package.json /app/package.json
COPY app/tsconfig.json /app/tsconfig.json
COPY app/src/types/helpers.ts /app/src/types/helpers.ts
COPY app/src/types/IsMatching.ts /app/src/types/IsMatching.ts
COPY app/src/types/BuildMany.ts /app/src/types/BuildMany.ts
COPY app/src/types/DistributeUnions.ts /app/src/types/DistributeUnions.ts
COPY app/src/types/DeepExclude.ts /app/src/types/DeepExclude.ts
COPY app/tests/type-checks.ts /app/tests/type-checks.ts
COPY app/tests/utils.ts /app/tests/utils.ts
WORKDIR /app
