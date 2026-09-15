
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip make && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY ml_ast.py /app/ml_ast.py
COPY ml_types.py /app/ml_types.py
COPY ml_unify.py /app/ml_unify.py
COPY ml_infer.py /app/ml_infer.py
COPY ml_parser.py /app/ml_parser.py
COPY ml_cli.py /app/ml_cli.py
COPY grammar.lark /app/grammar.lark
COPY Makefile /app/Makefile

WORKDIR /app
