
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install lark==1.1.9

RUN mkdir -p /app/examples

COPY ast_nodes.py /app/ast_nodes.py
COPY grammar.lark /app/grammar.lark
COPY transform.py /app/transform.py
COPY parser.py /app/parser.py
COPY eval.py /app/eval.py
COPY run.py /app/run.py
COPY run_all.py /app/run_all.py
COPY examples/ /app/examples/

WORKDIR /app
