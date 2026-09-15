FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y nodejs npm python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/tests

COPY package.json /app/package.json
COPY tsconfig.json /app/tsconfig.json
COPY src/arithmetic.ts /app/src/arithmetic.ts
COPY src/stack-machine.ts /app/src/stack-machine.ts
COPY src/parser.ts /app/src/parser.ts
COPY tests/test-arithmetic.ts /app/tests/test-arithmetic.ts
COPY tests/test-stack-ops.ts /app/tests/test-stack-ops.ts
COPY tests/test-parser.ts /app/tests/test-parser.ts
COPY tests/test-programs.ts /app/tests/test-programs.ts
COPY tests/test-conditionals.ts /app/tests/test-conditionals.ts

WORKDIR /app
