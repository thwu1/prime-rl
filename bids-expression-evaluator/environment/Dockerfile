FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/spec

COPY app/package.json app/package-lock.json app/tsconfig.json /app/
COPY app/run_tests.ts app/validate.ts app/resolve.ts /app/
COPY app/src/types.ts app/src/lexer.ts app/src/parser.ts app/src/evaluator.ts app/src/functions.ts app/src/index.ts app/src/rule_engine.ts app/src/inheritance.ts /app/src/
COPY app/spec/expression_tests.yaml app/spec/validation_rules.yaml app/spec/test_contexts.json app/spec/inheritance_tests.json /app/spec/

WORKDIR /app
